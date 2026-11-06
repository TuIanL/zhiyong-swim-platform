"""验证安装后的包，避免pytest的源码pythonpath掩盖打包/根目录问题。"""
import subprocess
import sys
from swimplatform.config import ROOT


def test_installed_package_finds_new_project_from_other_directory(tmp_path):
    result = subprocess.run(
        [sys.executable, "-I", "-c", "from swimplatform.config import ROOT; print(ROOT)"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(ROOT)
