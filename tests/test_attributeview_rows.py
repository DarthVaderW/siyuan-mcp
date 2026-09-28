"""Offline AttributeView rows regression tests."""

from __future__ import annotations
import unittest
from unittest import mock
from siyuan_mcp import attributeview_rows, core


class AttributeViewRowsTest(unittest.TestCase):
    def test_set_relation_cell_resolves_target_doc_to_target_item(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-source",
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                    "relation": {"avID": "20260605120000-people", "isTwoWay": False},
                                }
                            }
                        ],
                    }
                }
            if endpoint == "/api/av/getAttributeViewItemIDsByBoundIDs":
                self.assertEqual(payload["avID"], "20260605120000-people")
                self.assertEqual(payload["blockIDs"], ["20260605120000-person1"])
                return {"20260605120000-person1": "20260605120000-person-row"}
            if endpoint == "/api/av/setAttributeViewBlockAttr":
                value = payload["value"]
                self.assertEqual(value["relation"]["blockIDs"], ["20260605120000-person-row"])
                return None
            if endpoint == "/api/av/renderAttributeView":
                return {
                    "rows": [
                        {
                            "values": [
                                {
                                    "keyID": "20260605120000-rela01",
                                    "blockID": "20260605120000-paper-row",
                                    "relation": {
                                        "blockIDs": ["20260605120000-person-row"],
                                        "contents": [{"block": {"content": "Hanwen Wang"}}],
                                    },
                                }
                            ]
                        }
                    ]
                }
            raise AssertionError(endpoint)

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            result = attributeview_rows.siyuan_av_set_relation_cell(
                "20260605120000-source",
                "20260605120000-rela01",
                "20260605120000-paper-row",
                targetBlockIds=["20260605120000-person1"],
            )

        self.assertEqual(result["targetItemIds"], ["20260605120000-person-row"])
        self.assertEqual(result["itemIdsByBlockId"], {"20260605120000-person1": "20260605120000-person-row"})
        self.assertTrue(result["renderValidation"]["ok"])

    def test_set_relation_cell_rejects_unbound_target_doc(self):
        def fake_call(endpoint, payload):
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-source",
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                    "relation": {"avID": "20260605120000-people", "isTwoWay": False},
                                }
                            }
                        ],
                    }
                }
            if endpoint == "/api/av/getAttributeViewItemIDsByBoundIDs":
                self.assertEqual(payload["blockIDs"], ["20260605120000-person1"])
                return {}
            raise AssertionError(endpoint)

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            with self.assertRaisesRegex(ValueError, "Could not resolve target"):
                attributeview_rows.siyuan_av_set_relation_cell(
                    "20260605120000-source",
                    "20260605120000-rela01",
                    "20260605120000-paper-row",
                    targetBlockIds=["20260605120000-person1"],
                )

    def test_set_relation_cell_render_warning_does_not_fail_by_default(self):
        def fake_call(endpoint, _payload):
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-source",
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                    "relation": {"avID": "20260605120000-people", "isTwoWay": False},
                                }
                            }
                        ],
                    }
                }
            if endpoint == "/api/av/setAttributeViewBlockAttr":
                return None
            if endpoint == "/api/av/renderAttributeView":
                return {"rows": []}
            raise AssertionError(endpoint)

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            result = attributeview_rows.siyuan_av_set_relation_cell(
                "20260605120000-source",
                "20260605120000-rela01",
                "20260605120000-paper-row",
                targetItemIds=["20260605120000-person-row"],
            )
            with self.assertRaisesRegex(ValueError, "rendered relation.contents"):
                attributeview_rows.siyuan_av_set_relation_cell(
                    "20260605120000-source",
                    "20260605120000-rela01",
                    "20260605120000-paper-row",
                    targetItemIds=["20260605120000-person-row"],
                    requireRenderedContents=True,
                )

        self.assertFalse(result["renderValidation"]["ok"])
        self.assertTrue(result["warnings"])

    def test_plain_cell_tools_refuse_relation_fields(self):
        def fake_call(endpoint, _payload):
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-source",
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                    "relation": {"avID": "20260605120000-people", "isTwoWay": False},
                                }
                            }
                        ],
                    }
                }
            raise AssertionError(endpoint)

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            with self.assertRaisesRegex(ValueError, "siyuan_av_set_relation_cell"):
                attributeview_rows.siyuan_av_set_cell(
                    "20260605120000-source",
                    "20260605120000-rela01",
                    "20260605120000-paper-row",
                    ["20260605120000-person-doc"],
                )
            with self.assertRaisesRegex(ValueError, "siyuan_av_set_relation_cell"):
                attributeview_rows.siyuan_av_batch_set_cells(
                    "20260605120000-source",
                    [
                        {
                            "keyId": "20260605120000-rela01",
                            "itemId": "20260605120000-paper-row",
                            "value": ["20260605120000-person-doc"],
                        }
                    ],
                )

    def test_select_cell_reuses_or_assigns_non_empty_colors(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-av00001",
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-select1",
                                    "name": "状态",
                                    "type": "select",
                                    "options": [{"name": "追踪中", "color": "4"}],
                                }
                            }
                        ],
                    }
                }
            if endpoint == "/api/av/setAttributeViewBlockAttr":
                return None
            raise AssertionError(endpoint)

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            known = attributeview_rows.siyuan_av_set_cell(
                "20260605120000-av00001",
                "20260605120000-select1",
                "20260605120000-row0001",
                "追踪中",
            )
            new = attributeview_rows.siyuan_av_set_cell(
                "20260605120000-av00001",
                "20260605120000-select1",
                "20260605120000-row0001",
                "待验收",
            )

        self.assertEqual(known["value"]["mSelect"], [{"content": "追踪中", "color": "4"}])
        self.assertTrue(new["value"]["mSelect"][0]["color"])


if __name__ == "__main__":
    unittest.main()
