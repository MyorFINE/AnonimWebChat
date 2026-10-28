import os
import sys
import tempfile
from pathlib import Path

# Sozlamalar import vaqtida o'qiladi, shuning uchun vaqtinchalik data papkasini oldindan belgilaymiz.
os.environ["TERMCHAT_DATA_DIR"] = tempfile.mkdtemp(prefix="termchat-test-")
os.environ["TERMCHAT_MSG_RATE_COUNT"] = "50"
os.environ["TERMCHAT_ADMIN_PASSWORD"] = "owner-pass-1"
os.environ["TERMCHAT_REQUIRE_E2EE"] = "0"             # eski (ochiq matnli) testlar; E2EE testlari test_e2ee.py da qat'iy rejimni yoqadi
os.environ["TERMCHAT_REQUIRE_TUNNEL"] = "0"          # eski testlar to'g'ridan-to'g'ri chaqiradi; kanal testlari alohida (test_secure.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
