#!/usr/bin/env python3
"""No-secret tests for SiYuan AttributeView helpers."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from siyuan_mcp import attributeview


class AttributeViewToolsTest(unittest.TestCase):
    def test_create_table_initializes_block_and_fields(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/block/appendBlock":
                return [{"doOperations": [{"id": "20260605120000-avblock"}]}]
            if endpoint == "/api/av/renderAttributeView":
                return {
                    "id": "20260605120000-av00001",
                    "viewID": "20260605120000-view001",
                    "view": {
                        "id": "20260605120000-view001",
                        "columns": [
                            {"id": "20260605120000-primary", "name": "主键", "type": "block"},
                            {"id": "20260605120000-select1", "name": "单选", "type": "select"},
                        ],
                    },
                }
            if endpoint == "/api/attr/getBlockAttrs":
                return {}
            if endpoint == "/api/block/getBlockKramdown":
                return {
                    "kramdown": (
                        '<div data-type="NodeAttributeView" '
                        'data-av-id="20260605120000-av00001" '
                        'data-av-type="table"></div>'
                    )
                }
            if endpoint in {
                "/api/av/removeAttributeViewKey",
                "/api/av/addAttributeViewKey",
            }:
                return None
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_create_table(
                "20260605115959-parent1",
                avId="20260605120000-av00001",
                fields=[
                    {"id": "20260605120000-title01", "name": "标题", "type": "text"},
                    {"id": "20260605120000-url0001", "name": "arXiv", "type": "url"},
                ],
            )

        self.assertEqual(result["avId"], "20260605120000-av00001")
        self.assertEqual(result["requestedAvId"], "20260605120000-av00001")
        self.assertEqual(result["databaseBlockId"], "20260605120000-avblock")
        self.assertEqual(result["viewId"], "20260605120000-view001")
        self.assertEqual(result["primaryKeyId"], "20260605120000-primary")
        self.assertTrue(result["removedDefaultSelect"])
        self.assertEqual([field["keyId"] for field in result["addedFields"]], [
            "20260605120000-title01",
            "20260605120000-url0001",
        ])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(calls[0][0], "/api/block/appendBlock")
        self.assertIn('data-type="NodeAttributeView"', calls[0][1]["data"])
        self.assertIn('data-av-id="20260605120000-av00001"', calls[0][1]["data"])
        self.assertIn('data-av-type="table"', calls[0][1]["data"])
        self.assertEqual(calls[2][0], "/api/attr/getBlockAttrs")
        self.assertEqual(calls[3][0], "/api/block/getBlockKramdown")
        self.assertEqual(calls[4][0], "/api/av/removeAttributeViewKey")
        self.assertEqual(calls[5][1]["previousKeyID"], "20260605120000-primary")
        self.assertEqual(calls[6][1]["previousKeyID"], "20260605120000-title01")

    def test_create_table_tolerates_render_without_view(self):
        def fake_call(endpoint, _payload):
            if endpoint == "/api/block/appendBlock":
                return [{"id": "20260605120000-avblock"}]
            if endpoint == "/api/av/renderAttributeView":
                return {}
            if endpoint == "/api/attr/getBlockAttrs":
                return {}
            if endpoint == "/api/block/getBlockKramdown":
                return {}
            if endpoint == "/api/av/addAttributeViewKey":
                return None
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_create_table(
                "20260605115959-parent1",
                avId="20260605120000-av00001",
                fields=[{"id": "20260605120000-title01", "name": "标题", "type": "text"}],
                removeDefaultSelect=False,
            )

        self.assertEqual(result["avId"], "20260605120000-av00001")
        self.assertIsNone(result["viewId"])
        self.assertIsNone(result["primaryKeyId"])
        self.assertIn("Could not identify", result["warnings"][0])

    def test_create_table_uses_actual_av_id_from_inserted_block(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/block/appendBlock":
                return [{"id": "20260605120000-avblock"}]
            if endpoint == "/api/av/renderAttributeView":
                return {
                    "viewID": "20260605120000-view001",
                    "view": {
                        "columns": [
                            {"id": "20260605120000-primary", "name": "主键", "type": "block"},
                        ],
                    },
                }
            if endpoint == "/api/attr/getBlockAttrs":
                return {}
            if endpoint == "/api/block/getBlockKramdown":
                return {
                    "kramdown": (
                        '<div data-type="NodeAttributeView" '
                        'data-av-id="20260605120000-actual1" '
                        'data-av-type="table"></div>'
                    )
                }
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_create_table(
                "20260605115959-parent1",
                avId="20260605120000-request",
                fields=[],
                removeDefaultSelect=False,
            )

        self.assertEqual(result["avId"], "20260605120000-actual1")
        self.assertEqual(result["requestedAvId"], "20260605120000-request")
        self.assertIn("different av id", result["warnings"][0])
        self.assertEqual(calls[0][0], "/api/block/appendBlock")
        render_payloads = [payload for endpoint, payload in calls if endpoint == "/api/av/renderAttributeView"]
        self.assertEqual(render_payloads[0]["id"], "20260605120000-request")
        self.assertEqual(render_payloads[1]["id"], "20260605120000-actual1")


if __name__ == "__main__":
    unittest.main()
