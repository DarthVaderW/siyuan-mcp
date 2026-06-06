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

    def test_set_name_uses_transaction_operation(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/transactions":
                return [{"doOperations": payload["transactions"][0]["doOperations"]}]
            if endpoint == "/api/av/getAttributeView":
                return {"av": {"id": "20260605120000-av00001", "name": "论文总表"}}
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_set_name("20260605120000-av00001", "论文总表")

        self.assertEqual(result["name"], "论文总表")
        self.assertEqual(calls[0][0], "/api/transactions")
        operation = calls[0][1]["transactions"][0]["doOperations"][0]
        self.assertEqual(operation["action"], "setAttrViewName")
        self.assertEqual(operation["id"], "20260605120000-av00001")
        self.assertEqual(operation["data"], "论文总表")

    def test_set_view_name_uses_view_transaction_operation(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                view_name = "阅读队列" if any(call[0] == "/api/transactions" for call in calls) else "表格"
                return {
                    "av": {
                        "id": "20260605120000-av00001",
                        "views": [{"id": "20260605120000-view01", "name": view_name, "type": "table"}],
                    }
                }
            if endpoint == "/api/transactions":
                return [{"doOperations": payload["transactions"][0]["doOperations"]}]
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_set_view_name(
                "20260605120000-av00001",
                "20260605120000-view01",
                "阅读队列",
            )

        self.assertEqual(result["name"], "阅读队列")
        operation = [payload for endpoint, payload in calls if endpoint == "/api/transactions"][0][
            "transactions"
        ][0]["doOperations"][0]
        self.assertEqual(operation["action"], "setAttrViewViewName")
        self.assertEqual(operation["avID"], "20260605120000-av00001")
        self.assertEqual(operation["id"], "20260605120000-view01")
        self.assertEqual(operation["data"], "阅读队列")

    def test_duplicate_view_uses_frontend_transaction_shape(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                views = [{"id": "20260605120000-source", "name": "表格", "type": "table"}]
                if any(call[0] == "/api/transactions" for call in calls):
                    views.append({"id": "20260605120000-newview", "name": "表格 2", "type": "table"})
                return {"av": {"id": "20260605120000-av00001", "views": views}}
            if endpoint == "/api/transactions":
                return [{"doOperations": payload["transactions"][0]["doOperations"]}]
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_duplicate_view(
                "20260605120000-av00001",
                "20260605120000-avblock",
                "20260605120000-source",
                viewId="20260605120000-newview",
            )

        self.assertEqual(result["viewId"], "20260605120000-newview")
        operation = [payload for endpoint, payload in calls if endpoint == "/api/transactions"][0][
            "transactions"
        ][0]["doOperations"][0]
        self.assertEqual(operation["action"], "duplicateAttrViewView")
        self.assertEqual(operation["avID"], "20260605120000-av00001")
        self.assertEqual(operation["previousID"], "20260605120000-source")
        self.assertEqual(operation["id"], "20260605120000-newview")
        self.assertEqual(operation["blockID"], "20260605120000-avblock")

    def test_add_view_and_set_active_view_use_frontend_transaction_shapes(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                views = [{"id": "20260605120000-view01", "name": "表格", "type": "table"}]
                if any(call[0] == "/api/transactions" for call in calls):
                    views.append({"id": "20260605120000-view02", "name": "表格 2", "type": "table"})
                return {"av": {"id": "20260605120000-av00001", "views": views}}
            if endpoint == "/api/transactions":
                return [{"doOperations": payload["transactions"][0]["doOperations"]}]
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            add_result = attributeview.siyuan_av_add_view(
                "20260605120000-av00001",
                "20260605120000-avblock",
                viewId="20260605120000-view02",
            )
            active_result = attributeview.siyuan_av_set_active_view(
                "20260605120000-av00001",
                "20260605120000-avblock",
                "20260605120000-view02",
            )

        self.assertEqual(add_result["viewId"], "20260605120000-view02")
        self.assertEqual(active_result["viewId"], "20260605120000-view02")
        first_operation = [payload for endpoint, payload in calls if endpoint == "/api/transactions"][0][
            "transactions"
        ][0]["doOperations"][0]
        self.assertEqual(first_operation["action"], "addAttrViewView")
        self.assertEqual(first_operation["avID"], "20260605120000-av00001")
        self.assertEqual(first_operation["id"], "20260605120000-view02")
        self.assertEqual(first_operation["blockID"], "20260605120000-avblock")
        second_operation = [payload for endpoint, payload in calls if endpoint == "/api/transactions"][1][
            "transactions"
        ][0]["doOperations"][0]
        self.assertEqual(second_operation["action"], "setAttrViewBlockView")
        self.assertEqual(second_operation["avID"], "20260605120000-av00001")
        self.assertEqual(second_operation["id"], "20260605120000-view02")
        self.assertEqual(second_operation["blockID"], "20260605120000-avblock")

    def test_configure_table_view_orders_hides_and_sets_widths(self):
        calls = []
        attr_view = {
            "av": {
                "id": "20260605120000-av00001",
                "keyValues": [
                    {"key": {"id": "20260605120000-paper", "name": "论文", "type": "block"}},
                    {"key": {"id": "20260605120000-status", "name": "阅读状态", "type": "select"}},
                    {"key": {"id": "20260605120000-venue", "name": "Venue", "type": "select"}},
                    {"key": {"id": "20260605120000-zotero", "name": "Zotero", "type": "url"}},
                    {"key": {"id": "20260605120000-pdf", "name": "PDF Key", "type": "text"}},
                ],
                "views": [
                    {
                        "id": "20260605120000-view01",
                        "name": "表格",
                        "type": "table",
                        "table": {
                            "columns": [
                                {"id": "20260605120000-paper", "hidden": False, "pin": False, "wrap": False},
                                {"id": "20260605120000-status", "hidden": False, "pin": False, "wrap": False},
                                {"id": "20260605120000-venue", "hidden": False, "pin": False, "wrap": False},
                                {"id": "20260605120000-zotero", "hidden": True, "pin": False, "wrap": False},
                                {"id": "20260605120000-pdf", "hidden": False, "pin": False, "wrap": False},
                            ]
                        },
                    }
                ],
            }
        }

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                return attr_view
            if endpoint == "/api/transactions":
                return [{"doOperations": payload["transactions"][0]["doOperations"]}]
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_configure_table_view(
                "20260605120000-av00001",
                "20260605120000-avblock",
                "20260605120000-view01",
                [
                    {"keyNameCandidates": ["论文", "主键"], "width": "360px", "pin": True},
                    "阅读状态",
                    {"keyName": "Zotero", "width": "180px", "wrap": True},
                ],
                name="阅读队列",
                hideUnlisted=True,
                showIcon=True,
                wrapField=False,
                hideAttrViewName=False,
            )

        self.assertEqual([column["keyName"] for column in result["configuredColumns"]], ["论文", "阅读状态", "Zotero"])
        operations = [payload for endpoint, payload in calls if endpoint == "/api/transactions"][0][
            "transactions"
        ][0]["doOperations"]
        self.assertEqual(operations[0]["action"], "setAttrViewBlockView")
        self.assertEqual(operations[0]["id"], "20260605120000-view01")
        self.assertEqual(operations[1]["action"], "setAttrViewViewName")
        self.assertEqual(operations[1]["data"], "阅读队列")
        self.assertIn(
            {
                "action": "setAttrViewColHidden",
                "id": "20260605120000-venue",
                "avID": "20260605120000-av00001",
                "data": True,
                "blockID": "20260605120000-avblock",
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "setAttrViewColHidden",
                "id": "20260605120000-pdf",
                "avID": "20260605120000-av00001",
                "data": True,
                "blockID": "20260605120000-avblock",
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "sortAttrViewCol",
                "avID": "20260605120000-av00001",
                "previousID": "",
                "id": "20260605120000-paper",
                "blockID": "20260605120000-avblock",
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "setAttrViewColWidth",
                "id": "20260605120000-paper",
                "avID": "20260605120000-av00001",
                "data": "360px",
                "blockID": "20260605120000-avblock",
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "setAttrViewShowIcon",
                "avID": "20260605120000-av00001",
                "blockID": "20260605120000-avblock",
                "data": True,
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "setAttrViewWrapField",
                "avID": "20260605120000-av00001",
                "blockID": "20260605120000-avblock",
                "data": False,
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "hideAttrViewName",
                "avID": "20260605120000-av00001",
                "blockID": "20260605120000-avblock",
                "data": False,
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "setAttrViewColPin",
                "id": "20260605120000-paper",
                "avID": "20260605120000-av00001",
                "data": True,
                "blockID": "20260605120000-avblock",
                "viewID": "20260605120000-view01",
            },
            operations,
        )
        self.assertIn(
            {
                "action": "setAttrViewColWrap",
                "id": "20260605120000-zotero",
                "avID": "20260605120000-av00001",
                "data": True,
                "blockID": "20260605120000-avblock",
                "viewID": "20260605120000-view01",
            },
            operations,
        )

    def test_configure_relation_uses_target_av_transaction(self):
        calls = []

        def fake_call(endpoint, payload):
            calls.append((endpoint, payload))
            if endpoint == "/api/av/getAttributeView":
                if len([call for call in calls if call[0] == endpoint]) == 1:
                    return {
                        "av": {
                            "id": "20260605120000-source",
                            "keyValues": [
                                {"key": {"id": "20260605120000-rela01", "name": "关键人物", "type": "relation"}}
                            ],
                        }
                    }
                return {
                    "av": {
                        "id": "20260605120000-source",
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                    "relation": {"avID": "20260605120000-target", "isTwoWay": False},
                                }
                            }
                        ],
                    }
                }
            if endpoint == "/api/transactions":
                return None
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_configure_relation(
                "20260605120000-source",
                "20260605120000-rela01",
                "20260605120000-target",
            )

        self.assertEqual(result["targetAvId"], "20260605120000-target")
        operation = [payload for endpoint, payload in calls if endpoint == "/api/transactions"][0][
            "transactions"
        ][0]["doOperations"][0]
        self.assertEqual(operation["action"], "updateAttrViewColRelation")
        self.assertEqual(operation["avID"], "20260605120000-source")
        self.assertEqual(operation["id"], "20260605120000-target")
        self.assertEqual(operation["keyID"], "20260605120000-rela01")
        self.assertEqual(operation["format"], "关键人物")

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

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_set_relation_cell(
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

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            with self.assertRaisesRegex(ValueError, "Could not resolve target"):
                attributeview.siyuan_av_set_relation_cell(
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

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_set_relation_cell(
                "20260605120000-source",
                "20260605120000-rela01",
                "20260605120000-paper-row",
                targetItemIds=["20260605120000-person-row"],
            )
            with self.assertRaisesRegex(ValueError, "rendered relation.contents"):
                attributeview.siyuan_av_set_relation_cell(
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

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            with self.assertRaisesRegex(ValueError, "siyuan_av_set_relation_cell"):
                attributeview.siyuan_av_set_cell(
                    "20260605120000-source",
                    "20260605120000-rela01",
                    "20260605120000-paper-row",
                    ["20260605120000-person-doc"],
                )
            with self.assertRaisesRegex(ValueError, "siyuan_av_set_relation_cell"):
                attributeview.siyuan_av_batch_set_cells(
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

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            known = attributeview.siyuan_av_set_cell(
                "20260605120000-av00001",
                "20260605120000-select1",
                "20260605120000-row0001",
                "追踪中",
            )
            new = attributeview.siyuan_av_set_cell(
                "20260605120000-av00001",
                "20260605120000-select1",
                "20260605120000-row0001",
                "待验收",
            )

        self.assertEqual(known["value"]["mSelect"], [{"content": "追踪中", "color": "4"}])
        self.assertTrue(new["value"]["mSelect"][0]["color"])

    def test_summary_returns_bound_row_mapping(self):
        def fake_call(endpoint, _payload):
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-av00001",
                        "name": "人物总表",
                        "keyIDs": ["20260605120000-primary", "20260605120000-role01"],
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-primary",
                                    "name": "主键",
                                    "type": "block",
                                },
                                "values": [
                                    {
                                        "blockID": "20260605120000-person-row",
                                        "block": {"id": "20260605120000-person-doc", "content": "Hanwen Wang"},
                                    }
                                ],
                            },
                            {
                                "key": {
                                    "id": "20260605120000-role01",
                                    "name": "角色",
                                    "type": "text",
                                }
                            },
                        ],
                        "views": [{"id": "20260605120000-view01", "name": "表格", "type": "table"}],
                    }
                }
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_summary("20260605120000-av00001")

        self.assertEqual(result["name"], "人物总表")
        self.assertEqual(result["rowCount"], 1)
        self.assertEqual(
            result["itemIdsByBoundId"],
            {"20260605120000-person-doc": "20260605120000-person-row"},
        )
        self.assertEqual(
            result["boundIdsByItemId"],
            {"20260605120000-person-row": "20260605120000-person-doc"},
        )

    def test_summary_includes_relation_keys_omitted_from_keyids(self):
        def fake_call(endpoint, _payload):
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-av00001",
                        "name": "论文总表",
                        "keyIDs": [
                            "20260605120000-primary",
                            "20260605120000-status",
                        ],
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-primary",
                                    "name": "主键",
                                    "type": "block",
                                }
                            },
                            {
                                "key": {
                                    "id": "20260605120000-status",
                                    "name": "阅读状态",
                                    "type": "select",
                                    "options": [{"name": "待读", "color": "6"}],
                                }
                            },
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                    "relation": {"avID": "20260605120000-people"},
                                }
                            },
                        ],
                        "views": [
                            {
                                "id": "20260605120000-view01",
                                "name": "表格",
                                "type": "table",
                                "table": {
                                    "columns": [
                                        {"id": "20260605120000-primary"},
                                        {"id": "20260605120000-rela01"},
                                        {"id": "20260605120000-status"},
                                    ]
                                },
                            }
                        ],
                    }
                }
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_summary("20260605120000-av00001", includeRows=False)

        keys = result["keys"]
        self.assertEqual(
            [key["id"] for key in keys],
            [
                "20260605120000-primary",
                "20260605120000-rela01",
                "20260605120000-status",
            ],
        )
        relation_key = keys[1]
        self.assertEqual(relation_key["name"], "关键人物")
        self.assertEqual(relation_key["type"], "relation")
        self.assertEqual(relation_key["relationTargetAvId"], "20260605120000-people")

    def test_validate_schema_reports_empty_name_relation_target_and_select_color(self):
        def fake_call(endpoint, _payload):
            if endpoint == "/api/av/getAttributeView":
                return {
                    "av": {
                        "id": "20260605120000-av00001",
                        "name": "",
                        "keyIDs": [
                            "20260605120000-rela01",
                            "20260605120000-select1",
                        ],
                        "keyValues": [
                            {
                                "key": {
                                    "id": "20260605120000-rela01",
                                    "name": "关键人物",
                                    "type": "relation",
                                }
                            },
                            {
                                "key": {
                                    "id": "20260605120000-select1",
                                    "name": "状态",
                                    "type": "select",
                                    "options": [{"name": "追踪中", "color": ""}],
                                }
                            },
                        ],
                    }
                }
            raise AssertionError(endpoint)

        with mock.patch.object(attributeview, "call_siyuan", side_effect=fake_call):
            result = attributeview.siyuan_av_validate_schema("20260605120000-av00001")

        codes = [issue["code"] for issue in result["issues"]]
        self.assertFalse(result["ok"])
        self.assertIn("missing-av-name", codes)
        self.assertIn("relation-without-target-av", codes)
        self.assertIn("select-option-empty-color", codes)


if __name__ == "__main__":
    unittest.main()
