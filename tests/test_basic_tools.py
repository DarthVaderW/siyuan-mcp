"""Exercise registered basic tools through MCP with the transport stubbed."""

import asyncio
import unittest
from unittest.mock import patch

from siyuan_mcp import core, server


def call_tool(name, arguments):
    _, structured = asyncio.run(server.mcp.call_tool(name, arguments))
    return structured


class BasicToolsTest(unittest.TestCase):
    def test_remove_document_verifies_and_uses_storage_path_fallback(self):
        remaining = {"id": "doc", "box": "notebook", "path": "/doc.sy"}
        with patch.object(core, "call_siyuan", side_effect=[None, None, [remaining], None, None, []]) as api:
            result = call_tool("siyuan_remove_doc_by_id", {"id": "doc"})

        self.assertTrue(result["removed"])
        self.assertIsNone(result["remaining"])
        self.assertEqual([c.args[0] for c in api.call_args_list], [
            "/api/filetree/removeDocByID", "/api/sqlite/flushTransaction",
            "/api/query/sql", "/api/filetree/removeDoc",
            "/api/sqlite/flushTransaction", "/api/query/sql",
        ])
        self.assertEqual(api.call_args_list[3].args[1], {"notebook": "notebook", "path": "/doc.sy"})

    def test_ensure_existing_document_sets_attributes_without_creating(self):
        notebook = "20260929000000-abcdefg"
        with patch.object(core, "call_siyuan", side_effect=[["doc"], None]) as api:
            result = call_tool("siyuan_ensure_doc", {
                "path": "Notes//Example", "notebook": notebook,
                "markdown": "unused", "attrs": {"custom-state": "ready"},
            })

        self.assertFalse(result["created"])
        self.assertEqual(result["id"], "doc")
        self.assertEqual(result["path"], "/Notes/Example")
        self.assertEqual([c.args for c in api.call_args_list], [
            ("/api/filetree/getIDsByHPath", {"notebook": notebook, "path": "/Notes/Example"}),
            ("/api/attr/setBlockAttrs", {"id": "doc", "attrs": {"custom-state": "ready"}}),
        ])

    def test_move_document_resolves_both_paths_and_flushes(self):
        notebook = "20260929000000-abcdefg"
        with patch.object(core, "call_siyuan", side_effect=[["source"], ["target"], None, None]) as api:
            result = call_tool("siyuan_move_doc_by_path", {
                "path": "/Source", "toParentPath": "/Target", "notebook": notebook,
            })

        self.assertEqual(result["fromIds"], ["source"])
        self.assertEqual(result["toId"], "target")
        self.assertEqual([c.args for c in api.call_args_list], [
            ("/api/filetree/getIDsByHPath", {"notebook": notebook, "path": "/Source"}),
            ("/api/filetree/getIDsByHPath", {"notebook": notebook, "path": "/Target"}),
            ("/api/filetree/moveDocsByID", {"fromIDs": ["source"], "toID": "target"}),
            ("/api/sqlite/flushTransaction", {}),
        ])

    def test_notebook_and_block_tools_share_the_registered_transport(self):
        with patch.object(core, "call_siyuan", side_effect=[
            [{"id": "notebook", "name": "CodeX", "closed": False, "private": "omitted"}],
            [{"doOperations": [{"id": "block"}]}],
        ]) as api:
            notebooks = call_tool("siyuan_list_notebooks", {})
            inserted = call_tool("siyuan_insert_block", {"parentId": "doc", "data": "text"})

        self.assertEqual(notebooks, {"notebooks": [{"id": "notebook", "name": "CodeX", "closed": False}]})
        self.assertEqual(inserted["inserted"], ["block"])
        self.assertEqual(api.call_args_list[1].args, (
            "/api/block/appendBlock", {"parentID": "doc", "data": "text", "dataType": "markdown"},
        ))


if __name__ == "__main__":
    unittest.main()
