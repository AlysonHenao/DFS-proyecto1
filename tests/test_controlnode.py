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
sys.modules.pop("auth", None)
sys.modules.pop("config", None)
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

    def test_rf3_open_read_and_read_plan(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        # Create file via RF2
        blocks = [{"index": 0, "block_id": "b-read-1", "size": 65536, "chain": ["datanode1:50051", "datanode2:50051"]}]
        db.create_upload_plan(uid, "/rf3_read.bin", 65536, 65536, blocks, self.db_path)
        db.commit_upload(uid, "/rf3_read.bin", [{"block_id": "b-read-1", "stored_on": ["datanode1:50051", "datanode2:50051"]}], 2, self.db_path)

        # Open in read mode
        sess = db.open_file_session(uid, "/rf3_read.bin", mode="r", db_path=self.db_path)
        self.assertEqual(sess["mode"], "r")
        self.assertEqual(sess["base_version"], 1)

        # Get read plan
        plan = db.get_read_plan_rf3(uid, sess["session_id"], offset=100, length=500, db_path=self.db_path)
        self.assertEqual(plan["version"], 1)
        self.assertEqual(len(plan["blocks"]), 1)
        self.assertEqual(plan["blocks"][0]["block_id"], "b-read-1")
        self.assertEqual(plan["blocks"][0]["offset"], 0)

        # Close session
        res = db.commit_file_session(uid, sess["session_id"], db_path=self.db_path)
        self.assertEqual(res["status"], "closed")

    def test_rf3_exclusive_lock_and_concurrency(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        # Client 1 opens in mode 'w'
        sess1 = db.open_file_session(uid, "/shared.txt", mode="w", lease_seconds=10, db_path=self.db_path)
        self.assertEqual(sess1["mode"], "w")

        # Client 2 attempts to open same file in mode 'w' concurrently -> rejected
        with self.assertRaises(FileExistsError):
            db.open_file_session(uid, "/shared.txt", mode="w", db_path=self.db_path)

        # Client 1 renews lease
        renewed = db.renew_file_lease(uid, sess1["session_id"], lease_seconds=30, db_path=self.db_path)
        self.assertEqual(renewed["status"], "locked")

        # Client 1 unlocks
        db.unlock_file_session(uid, sess1["session_id"], db_path=self.db_path)

        # Now Client 2 can open in mode 'w'
        sess2 = db.open_file_session(uid, "/shared.txt", mode="w", lease_seconds=10, db_path=self.db_path)
        self.assertEqual(sess2["mode"], "w")
        self.assertNotEqual(sess1["session_id"], sess2["session_id"])

    def test_rf3_write_plan_copy_on_write_and_commit(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        # Open new file for write
        sess = db.open_file_session(uid, "/cow_test.txt", mode="w", db_path=self.db_path)
        self.assertEqual(sess["base_version"], 0)

        # Plan write
        plan = db.get_write_plan_rf3(uid, sess["session_id"], offset=0, length=1000, db_path=self.db_path)
        self.assertEqual(len(plan["blocks"]), 1)
        blk = plan["blocks"][0]

        # Commit write session with quorum
        commit_res = db.commit_file_session(
            uid,
            sess["session_id"],
            blocks=[{"index": 0, "block_id": blk["block_id"], "size": 1000, "stored_on": ["datanode1:50051", "datanode2:50051"]}],
            min_write_acks=2,
            db_path=self.db_path,
        )
        self.assertEqual(commit_res["status"], "closed")
        self.assertEqual(commit_res["version"], 1)
        self.assertEqual(commit_res["size"], 1000)

        # Verify new session sees version 1
        read_sess = db.open_file_session(uid, "/cow_test.txt", mode="r", db_path=self.db_path)
        self.assertEqual(read_sess["base_version"], 1)
        self.assertEqual(read_sess["size"], 1000)

    def test_rf3_cas_version_conflict(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        # Create version 1
        s1 = db.open_file_session(uid, "/conflict.txt", mode="w", db_path=self.db_path)
        p1 = db.get_write_plan_rf3(uid, s1["session_id"], 0, 500, db_path=self.db_path)
        db.commit_file_session(uid, s1["session_id"], [{"index": 0, "block_id": p1["blocks"][0]["block_id"], "size": 500, "stored_on": ["datanode1:50051", "datanode2:50051"]}], 2, self.db_path)

        # Client A opens file in 'w' based on version 1
        sess_a = db.open_file_session(uid, "/conflict.txt", mode="w", db_path=self.db_path)
        self.assertEqual(sess_a["base_version"], 1)
        plan_a = db.get_write_plan_rf3(uid, sess_a["session_id"], 0, 600, db_path=self.db_path)

        # Client A releases lock (simulating lock timeout or handoff)
        db.unlock_file_session(uid, sess_a["session_id"], db_path=self.db_path)

        # Client B opens and commits version 2
        sess_b = db.open_file_session(uid, "/conflict.txt", mode="w", db_path=self.db_path)
        plan_b = db.get_write_plan_rf3(uid, sess_b["session_id"], 0, 700, db_path=self.db_path)
        db.commit_file_session(uid, sess_b["session_id"], [{"index": 0, "block_id": plan_b["blocks"][0]["block_id"], "size": 700, "stored_on": ["datanode1:50051", "datanode2:50051"]}], 2, self.db_path)

        # Client A re-locks and attempts commit against base_version 1 -> CAS conflict
        db.lock_file_session(uid, sess_a["session_id"], 60, db_path=self.db_path)
        with self.assertRaises(ValueError) as ctx:
            db.commit_file_session(uid, sess_a["session_id"], [{"index": 0, "block_id": plan_a["blocks"][0]["block_id"], "size": 600, "stored_on": ["datanode1:50051", "datanode2:50051"]}], 2, self.db_path)
        self.assertIn("version conflict", str(ctx.exception))

    def test_rf3_lease_expiration_and_orphan_cleanup(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        # Open session with very short lease (1 second)
        sess = db.open_file_session(uid, "/expire.txt", mode="w", lease_seconds=1, db_path=self.db_path)
        plan = db.get_write_plan_rf3(uid, sess["session_id"], 0, 500, db_path=self.db_path)
        new_bid = plan["blocks"][0]["block_id"]

        # Sleep so lease expires
        time.sleep(1.5)

        # Clean expired
        locks_cleaned, expired = db.clean_expired_locks_and_sessions(self.db_path)
        self.assertGreater(locks_cleaned, 0)
        self.assertGreater(expired, 0)

        # The uncommitted block is purged from blocks table (meaning it's an orphan for DataNodes)
        orphans = db.get_orphan_blocks_for_node([new_bid], self.db_path)
        self.assertIn(new_bid, orphans)

        # Now another client can immediately open the file without conflict
        sess_new = db.open_file_session(uid, "/expire.txt", mode="w", db_path=self.db_path)
        self.assertEqual(sess_new["mode"], "w")

    def test_rf3_quorum_enforcement(self):
        user = db.get_user_by_username("demo", self.db_path)
        uid = user["id"]

        db.upsert_node("dn1", "datanode1:50051", 1000, 2000, self.db_path)
        db.upsert_node("dn2", "datanode2:50051", 900, 2000, self.db_path)

        sess = db.open_file_session(uid, "/quorum.txt", mode="w", db_path=self.db_path)
        plan = db.get_write_plan_rf3(uid, sess["session_id"], 0, 500, db_path=self.db_path)
        blk = plan["blocks"][0]

        # Only 1 confirmation when MIN_WRITE_ACKS=2
        with self.assertRaises(ValueError) as ctx:
            db.commit_file_session(
                uid,
                sess["session_id"],
                [{"index": 0, "block_id": blk["block_id"], "size": 500, "stored_on": ["datanode1:50051"]}],
                min_write_acks=2,
                db_path=self.db_path,
            )
        self.assertIn("confirmations", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


