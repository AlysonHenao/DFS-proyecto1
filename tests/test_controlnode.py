import os
from pathlib import Path
import tempfile
import time
import unittest

# Ensure dev mode environment for test
os.environ["DEV_MODE"] = "1"
os.environ["BLOCK_SIZE_BYTES"] = "65536"
os.environ["REPLICATION_FACTOR"] = "2"
os.environ["MIN_WRITE_ACKS"] = "2"
os.environ["DEAD_TIMEOUT_S"] = "2"

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "controlnode"))

import auth
import db


class TestControlNodeDatabase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "test_meta.db")
        self.schema_path = str(Path(__file__).parent.parent / "schema.sql")
        db.init_db(self.db_path, self.schema_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_demo_user_exists(self):
        user = db.get_user_by_username("demo", self.db_path)
        self.assertIsNotNone(user)
        self.assertTrue(auth.verify_password("demo", user["password_hash"]))

    def test_user_creation_and_auth(self):
        pwd_hash = auth.hash_password("secret123")
        created = db.create_user("alice", pwd_hash, self.db_path)
        self.assertEqual(created["username"], "alice")

        user = db.get_user_by_username("alice", self.db_path)
        self.assertIsNotNone(user)
        self.assertTrue(auth.verify_password("secret123", user["password_hash"]))
        self.assertFalse(auth.verify_password("wrong", user["password_hash"]))

        # JWT token check
        token = auth.create_access_token("alice")
        payload = auth.decode_access_token(token)
        self.assertEqual(payload["sub"], "alice")

    def test_directory_operations(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        # Make directory /docs
        res = db.create_directory(uid, "/docs", self.db_path)
        self.assertEqual(res["path"], "/docs")

        # Make nested directory /docs/sub
        res_sub = db.create_directory(uid, "/docs/sub", self.db_path)
        self.assertEqual(res_sub["path"], "/docs/sub")

        # Listing / should only show direct child 'docs'
        ls_root = db.list_directory(uid, "/", self.db_path)
        self.assertEqual(len(ls_root), 1)
        self.assertEqual(ls_root[0]["name"], "docs")
        self.assertEqual(ls_root[0]["type"], "dir")

        # Listing /docs should show 'sub'
        ls_docs = db.list_directory(uid, "/docs", self.db_path)
        self.assertEqual(len(ls_docs), 1)
        self.assertEqual(ls_docs[0]["name"], "sub")

        # Cannot remove non-empty directory /docs
        with self.assertRaises(FileExistsError):
            db.remove_directory(uid, "/docs", self.db_path)

        # Remove /docs/sub
        db.remove_directory(uid, "/docs/sub", self.db_path)

        # Now /docs is empty, can remove
        db.remove_directory(uid, "/docs", self.db_path)
        ls_after = db.list_directory(uid, "/", self.db_path)
        self.assertEqual(len(ls_after), 0)

    def test_file_upload_and_download_flow(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        # Register nodes
        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        # Plan upload
        blocks = [
            {"index": 0, "block_id": "blk-1", "size": 65536, "chain": ["datanode1:50051", "datanode2:50051"]},
            {"index": 1, "block_id": "blk-2", "size": 1024, "chain": ["datanode1:50051", "datanode2:50051"]},
        ]
        entry_id = db.create_upload_plan(uid, "/test.bin", 66560, 65536, blocks, self.db_path)
        self.assertGreater(entry_id, 0)

        # Not visible in ls while uploading
        ls_uploading = db.list_directory(uid, "/", self.db_path)
        self.assertEqual(len(ls_uploading), 0)

        # Commit upload with quorum
        commit_blocks = [
            {"index": 0, "block_id": "blk-1", "stored_on": ["datanode1:50051", "datanode2:50051"]},
            {"index": 1, "block_id": "blk-2", "stored_on": ["datanode1:50051", "datanode2:50051"]},
        ]
        db.commit_upload(uid, "/test.bin", commit_blocks, min_write_acks=2, db_path=self.db_path)

        # Visible in ls after commit
        ls_ready = db.list_directory(uid, "/", self.db_path)
        self.assertEqual(len(ls_ready), 1)
        self.assertEqual(ls_ready[0]["name"], "test.bin")
        self.assertEqual(ls_ready[0]["size"], 66560)

        # Get download plan
        plan = db.get_download_plan(uid, "/test.bin", self.db_path)
        self.assertIsNotNone(plan)
        self.assertEqual(plan["size"], 66560)
        self.assertEqual(len(plan["blocks"]), 2)
        self.assertEqual(set(plan["blocks"][0]["nodes"]), {"datanode1:50051", "datanode2:50051"})

        # Remove file
        db.remove_file(uid, "/test.bin", self.db_path)
        self.assertIsNone(db.get_download_plan(uid, "/test.bin", self.db_path))

    def test_node_failure_and_under_replicated_detection(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        blocks = [{"index": 0, "block_id": "blk-rep", "size": 100, "chain": ["datanode1:50051", "datanode2:50051"]}]
        db.create_upload_plan(uid, "/rep.txt", 100, 65536, blocks, self.db_path)
        db.commit_upload(uid, "/rep.txt", [{"index": 0, "block_id": "blk-rep", "stored_on": ["datanode1:50051", "datanode2:50051"]}], min_write_acks=2, db_path=self.db_path)

        # Initially, all 2 replicas alive
        under_rep = db.get_under_replicated_blocks(2, self.db_path)
        self.assertEqual(len(under_rep), 0)

        # Simulate timeout for dn2
        time.sleep(2.1)
        # Touch dn1 only
        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        dead = db.mark_dead_nodes(dead_timeout_s=2, db_path=self.db_path)
        self.assertIn("dn2", dead)

        # Now blk-rep has only 1 alive replica (dn1)
        under_rep = db.get_under_replicated_blocks(2, self.db_path)
        self.assertEqual(len(under_rep), 1)
        self.assertEqual(under_rep[0]["block_id"], "blk-rep")
        self.assertEqual(under_rep[0]["alive_addresses"], ["datanode1:50051"])

    def test_snapshot_backup_and_restore(self):
        user = db.get_user_by_username("demo", self.db_path)
        db.create_directory(user["id"], "/backup_test", self.db_path)

        snapshot = db.create_snapshot_bytes(self.db_path)
        self.assertGreater(len(snapshot), 0)

        # Restore into another file
        target_path = str(Path(self.temp_dir.name) / "restored.db")
        db.restore_from_snapshot_bytes(snapshot, target_path)

        # Check restored content
        res = db.list_directory(user["id"], "/", target_path)
        self.assertTrue(any(e["name"] == "backup_test" for e in res))


if __name__ == "__main__":
    unittest.main()
