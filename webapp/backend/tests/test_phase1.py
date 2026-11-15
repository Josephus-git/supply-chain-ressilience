"""Phase 1 backend tests: read-only client, home and graph endpoints, locations,
vector retrieval. They run against the live Neo4j in .env and are skipped if it
is unreachable. No OpenAI calls: retrieval uses a stored Product embedding as
the query vector.

    .venv/bin/python -m unittest discover -s webapp/backend/tests -t .
"""

from __future__ import annotations

import json
import unittest

import neo4j.exceptions

from webapp.backend.config import LOCATIONS_PATH
from webapp.backend.neo4j_client import ReadOnlyNeo4j

client: ReadOnlyNeo4j | None = None
http = None
_skip_reason = None


def setUpModule() -> None:
    global client, http, _skip_reason
    try:
        client = ReadOnlyNeo4j()
        client.verify()
    except Exception as e:  # pragma: no cover - environment dependent
        _skip_reason = f"Neo4j unavailable: {e}"
        raise unittest.SkipTest(_skip_reason)
    from fastapi.testclient import TestClient

    from webapp.backend.main import create_app

    http = TestClient(create_app(neo4j_client=client))
    http.__enter__()


def tearDownModule() -> None:
    if http is not None:
        http.__exit__(None, None, None)
    if client is not None:
        client.close()


def get(url: str, status: int = 200) -> dict:
    r = http.get(url)
    assert r.status_code == status, (url, r.status_code, r.text[:500])
    return r.json()


def count(cypher: str, **params) -> int:
    return client.read(cypher, params)[0]["n"]


class ReadOnlyTests(unittest.TestCase):
    def test_writes_are_rejected(self):
        before = count("MATCH (n) RETURN count(n) AS n")
        for cypher in (
            "CREATE (:WebAppWriteProbe {at: datetime()})",
            "MERGE (s:Supplier {supplier_id: 'org:write-probe'})",
            "MATCH (s:Supplier) SET s.write_probe = true",
            "MATCH (n:WebAppWriteProbe) DETACH DELETE n",
        ):
            with self.subTest(cypher=cypher), self.assertRaises(neo4j.exceptions.ClientError):
                client.read(cypher)
        self.assertEqual(before, count("MATCH (n) RETURN count(n) AS n"))
        self.assertEqual(0, count("MATCH (s:Supplier) WHERE s.write_probe IS NOT NULL RETURN count(s) AS n"))

    def test_log_records_query(self):
        log: list = []
        client.read("MATCH (s:Supplier) RETURN count(s) AS n", log=log, name="probe")
        self.assertEqual(1, len(log))
        self.assertEqual({"name", "cypher", "params", "row_count", "elapsed_ms"}, set(log[0]))
        self.assertEqual("probe", log[0]["name"])


class LocationsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ref = json.loads(LOCATIONS_PATH.read_text(encoding="utf-8"))

    def _check(self, entry):
        self.assertTrue(-90 <= entry["lat"] <= 90 and -180 <= entry["lon"] <= 180, entry)
        self.assertTrue(entry.get("basis"), entry)

    def test_every_supplier_and_buyer_located(self):
        suppliers = {r["id"] for r in client.read("MATCH (s:Supplier) RETURN s.supplier_id AS id")}
        buyers = {r["id"] for r in client.read("MATCH (b:Buyer) RETURN b.buyer_id AS id")}
        self.assertEqual(suppliers, set(self.ref["suppliers"]))
        self.assertEqual(buyers, set(self.ref["buyers"]))
        for entry in [*self.ref["suppliers"].values(), *self.ref["buyers"].values()]:
            self._check(entry)

    def test_every_port_without_coordinates_located(self):
        missing = {
            r["id"]
            for r in client.read(
                "MATCH (p:`Exit Port`) WHERE p.exit_port_lat IS NULL OR p.exit_port_lon IS NULL "
                "RETURN p.exit_port_id AS id"
            )
        }
        self.assertEqual(missing, set(self.ref["exit_ports"]))
        self.assertEqual(0, count(
            "MATCH (p:`Entry Port`) WHERE p.entry_port_lat IS NULL OR p.entry_port_lon IS NULL RETURN count(p) AS n"
        ))
        for entry in self.ref["exit_ports"].values():
            self._check(entry)
            if entry["level"] == "country":
                self.assertIn("country level", entry["label"])


class HomeTests(unittest.TestCase):
    def test_stats(self):
        s = get("/api/home/stats")
        self.assertEqual(count("MATCH (n:Supplier) RETURN count(n) AS n"), s["suppliers"])
        self.assertEqual(count("MATCH (n:Shipment) RETURN count(n) AS n"), s["shipments"])
        self.assertEqual(count("MATCH (n:Product) RETURN count(n) AS n"), s["products"])
        self.assertEqual(count("MATCH (n) WHERE n:`Exit Port` OR n:`Entry Port` RETURN count(n) AS n"), s["ports"])
        self.assertEqual(count("MATCH (n:Carrier) RETURN count(n) AS n"), s["carriers"])
        self.assertEqual(10, s["supplier_companies"])
        self.assertEqual(len(http.app.state.evidence_db.index.records), s["evidence_records"])
        self.assertEqual({"start": "2025-01-01", "end": "2026-09-30"}, s["study_window"])

    def test_network(self):
        n = get("/api/home/network")
        shipments = count("MATCH (n:Shipment) RETURN count(n) AS n")
        self.assertEqual([], n["missing_locations"])
        self.assertEqual(18, len(n["suppliers"]))
        self.assertEqual(5, len(n["buyers"]))
        self.assertEqual(shipments, sum(s["shipments"] for s in n["suppliers"]))
        self.assertEqual(shipments, sum(link["shipments"] for link in n["links"]))
        self.assertEqual(shipments, sum(r["shipments"] for r in n["routes"]))
        ids = {s["id"] for s in n["suppliers"]} | {b["id"] for b in n["buyers"]} | {p["id"] for p in n["ports"]}
        for r in n["routes"]:
            self.assertTrue({r["supplier"], r["exit_port"], r["entry_port"], r["buyer"]} <= ids, r)
        for s in n["suppliers"]:
            self.assertEqual(s["shipments"], sum(p["shipments"] for p in s["exit_ports"]), s["id"])
            self.assertIsNotNone(s["location"])
        ihastek = next(s for s in n["suppliers"] if s["supplier_id"] == "org:ihastek-malaysia-sdn-bhd")
        self.assertEqual("CN", ihastek["reported_country_code"])  # graph value kept ...
        self.assertEqual("MY", ihastek["location"]["country_code"])  # ... map uses the address

    def test_top_suppliers(self):
        t = get("/api/home/top-suppliers")
        self.assertEqual(21, len(t["months"]))
        self.assertEqual(("2025-01", "2026-09"), (t["months"][0], t["months"][-1]))
        self.assertEqual(10, len(t["series"]))
        totals = [s["total"] for s in t["series"]]
        self.assertEqual(sorted(totals, reverse=True), totals)
        self.assertEqual(count("MATCH (n:Shipment) RETURN count(n) AS n"), sum(totals))
        for s in t["series"]:
            self.assertEqual(21, len(s["monthly"]))
            self.assertEqual(s["total"], sum(s["monthly"]))
        self.assertEqual(18, sum(len(s["supplier_ids"]) for s in t["series"]))
        self.assertEqual(3, len(get("/api/home/top-suppliers?limit=3")["series"]))


class GraphTests(unittest.TestCase):
    NODE_KEYS = {"id", "kind", "label", "name", "properties"}

    def _check_graph(self, g):
        ids = [n["id"] for n in g["nodes"]]
        self.assertEqual(len(ids), len(set(ids)), "duplicate node IDs")
        for node in g["nodes"]:
            self.assertEqual(self.NODE_KEYS, set(node))
            self.assertNotIn("embedding", node["properties"])
        for e in g["edges"]:
            self.assertIn(e["source"], ids)
            self.assertIn(e["target"], ids)

    def test_supplier_picker(self):
        companies = get("/api/graph/suppliers")["companies"]
        self.assertEqual(10, len(companies))
        self.assertEqual(18, sum(len(c["suppliers"]) for c in companies))

    def test_default_snapshot_is_busiest_company(self):
        g = get("/api/graph/snapshot")
        self._check_graph(g)
        top = get("/api/home/top-suppliers?limit=1")["series"][0]
        self.assertEqual(sorted(top["supplier_ids"]), sorted(g["suppliers"]))

    def test_snapshot_counts_match_cypher(self):
        """VS Industry Berhad's two Supplier nodes; each shipment has one link of each type."""
        g = get("/api/graph/snapshot?suppliers=Vs%20Industrial%20Berhad")
        self._check_graph(g)
        self.assertEqual(["supplier:org:v-s-industrial-berhad", "supplier:org:vs-industrial-berhad"], g["suppliers"])
        expected = {
            r["sid"]: r["n"]
            for r in client.read(
                "MATCH (s:Supplier {supplier_basename: 'Vs Industrial Berhad'})-[:SHIPPED]->(sh) "
                "RETURN 'supplier:' + s.supplier_id AS sid, count(sh) AS n"
            )
        }
        for sid, n in expected.items():
            for rel in ("CONTAINS_PRODUCT", "DEPARTED_FROM", "ARRIVED_AT", "CARRIED_BY", "TRANSPORTED_ON", "CONSIGNED_TO"):
                total = sum(e["shipments"] for e in g["edges"] if e["source"] == sid and e["type"] == rel)
                self.assertEqual(n, total, (sid, rel))
        self.assertTrue(any(e["type"] == "SUBSIDIARY_OF" and not e["aggregated"] for e in g["edges"]))

    def test_snapshot_date_filter(self):
        g = get("/api/graph/snapshot?suppliers=org:v-s-industrial-berhad&date_from=2025-01-01&date_to=2025-06-30")
        n = count(
            "MATCH (:Supplier {supplier_id: 'org:v-s-industrial-berhad'})-[:SHIPPED]->(sh) "
            "WHERE date(sh.arrival_date) <= date('2025-06-30') RETURN count(sh) AS n"
        )
        got = sum(e["shipments"] for e in g["edges"] if e["type"] == "DEPARTED_FROM")
        self.assertEqual(n, got)
        get("/api/graph/snapshot?date_to=yesterday", status=400)
        get("/api/graph/snapshot?suppliers=nobody", status=404)

    def test_full_graph(self):
        g = get("/api/graph/snapshot?full=true")
        self.assertEqual(count("MATCH (n) RETURN count(n) AS n"), len(g["nodes"]))
        self.assertEqual(count("MATCH ()-[r]->() RETURN count(r) AS n"), len(g["edges"]))

    def test_neighbours(self):
        sid = "supplier:org:ihastek-malaysia-sdn-bhd"
        n = get(f"/api/graph/nodes/{sid}/neighbours?limit=5")
        self.assertEqual(sid, n["node"]["id"])
        self.assertEqual(5, len(n["edges"]))
        self.assertTrue(n["truncated"])
        self.assertEqual(count(
            "MATCH (:Supplier {supplier_id: 'org:ihastek-malaysia-sdn-bhd'})--(m) RETURN count(m) AS n"
        ), n["total"])
        # parent first, then shipments
        self.assertEqual("parent", n["neighbours"][0]["kind"])

        agg = get("/api/graph/nodes/exit_port:port:55750/neighbours?aggregate=true")
        self.assertTrue(agg["aggregate"])
        suppliers = {e["source"] for e in agg["edges"] if e["type"] == "SHIPPED"}
        self.assertIn(sid, suppliers)

        shipment = get("/api/graph/nodes/shipment:bol:kfunsjhb3002330/neighbours")
        self.assertEqual(7, len(shipment["edges"]))  # supplier + 6 outgoing relationships

        get("/api/graph/nodes/bogus/neighbours", status=400)
        get("/api/graph/nodes/supplier:org:nobody/neighbours", status=404)

    def test_edge_shipments_match_aggregate(self):
        sid, port = "supplier:org:ihastek-malaysia-sdn-bhd", "exit_port:port:55750"
        snap = get(f"/api/graph/snapshot?suppliers={sid}")
        edge = next(e for e in snap["edges"] if e["source"] == sid and e["target"] == port)
        expanded = get(f"/api/graph/edges/shipments?source={sid}&target={port}")
        self.assertEqual(edge["shipments"], expanded["count"])
        self.assertEqual(2 * expanded["count"], len(expanded["edges"]))

    def test_search(self):
        r = get("/api/graph/search?q=ihastek")
        self.assertEqual("supplier:org:ihastek-malaysia-sdn-bhd", r["results"][0]["id"])
        r = get("/api/graph/search?q=tanjung&kinds=exit_port")
        self.assertEqual(["exit_port:port:55750"], [x["id"] for x in r["results"]])
        get("/api/graph/search?q=x&kinds=planet", status=400)


class RetrieveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from webapp.backend.pipeline.retrieve import retrieve_products

        cls.retrieve = staticmethod(retrieve_products)
        cls.vector = client.read("MATCH (p:Product {product_id: 'hs:080610'}) RETURN p.embedding AS e")[0]["e"]

    def test_stored_embedding_finds_itself(self):
        r = self.retrieve(client, "vacuum cleaner", top_k=5, embedder=lambda _: self.vector)
        self.assertEqual(5, len(r.products))
        self.assertEqual("product:hs:080610", r.products[0].node_id)
        self.assertAlmostEqual(1.0, r.products[0].score, places=4)
        scores = [p.score for p in r.products]
        self.assertEqual(sorted(scores, reverse=True), scores)
        self.assertEqual(
            count("MATCH (:Product {product_id: 'hs:080610'})<-[:CONTAINS_PRODUCT]-(sh) RETURN count(sh) AS n"),
            r.products[0].shipments,
        )

    def test_trace_has_cypher_but_not_vector(self):
        log: list = []
        r = self.retrieve(client, "vacuum cleaner", top_k=3, embedder=lambda _: self.vector, log=log)
        self.assertEqual(log, r.queries)
        self.assertIn("SEARCH", log[0]["cypher"])
        self.assertEqual("vacuum cleaner", log[0]["params"]["query_text"])
        self.assertIsInstance(log[0]["params"]["query_vector"], str)
        json.dumps(r.to_dict())  # serialisable for runs/

    def test_as_of_date_limits_counts(self):
        r = self.retrieve(client, "vacuum", top_k=3, embedder=lambda _: self.vector, as_of_date="2025-06-30")
        self.assertEqual(0, r.products[0].shipments)  # its 3 shipments all arrive in 2026

    def test_min_score_and_validation(self):
        r = self.retrieve(client, "vacuum", top_k=10, min_score=0.99, embedder=lambda _: self.vector)
        self.assertEqual(["product:hs:080610"], [p.node_id for p in r.products])
        with self.assertRaises(ValueError):
            self.retrieve(client, "  ", embedder=lambda _: self.vector)


if __name__ == "__main__":
    unittest.main()
