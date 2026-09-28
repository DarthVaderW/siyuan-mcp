"""Offline AttributeView views regression tests."""

from __future__ import annotations
import unittest
from unittest import mock
from siyuan_mcp import attributeview_views, core


class AttributeViewViewsTest(unittest.TestCase):
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

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            result = attributeview_views.siyuan_av_set_view_name(
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

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            result = attributeview_views.siyuan_av_duplicate_view(
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

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            add_result = attributeview_views.siyuan_av_add_view(
                "20260605120000-av00001",
                "20260605120000-avblock",
                viewId="20260605120000-view02",
            )
            active_result = attributeview_views.siyuan_av_set_active_view(
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

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            result = attributeview_views.siyuan_av_configure_table_view(
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

    def test_configure_view_can_preserve_existing_visibility(self):
        view = {"id": "view", "type": "table", "table": {"columns": [
            {"id": "title", "hidden": False}, {"id": "notes", "hidden": True},
        ]}}
        schema = {"id": "av", "views": [view], "keyValues": [
            {"key": {"id": "title", "name": "Title", "type": "block"}},
            {"key": {"id": "notes", "name": "Notes", "type": "text"}},
        ]}
        transactions = []

        def fake_call(endpoint, payload):
            if endpoint == "/api/av/getAttributeView":
                return schema
            if endpoint == "/api/transactions":
                transactions.extend(payload["transactions"][0]["doOperations"])
                return None
            raise AssertionError(endpoint)

        with mock.patch.object(core, "call_siyuan", side_effect=fake_call):
            result = attributeview_views.siyuan_av_configure_table_view(
                "av", "block", "view", ["title"], hideUnlisted=False,
            )
        self.assertFalse(result["hiddenUnlisted"])
        self.assertEqual([op["action"] for op in transactions],
                         ["setAttrViewBlockView", "sortAttrViewCol"])
        self.assertTrue(view["table"]["columns"][1]["hidden"])


if __name__ == "__main__":
    unittest.main()
