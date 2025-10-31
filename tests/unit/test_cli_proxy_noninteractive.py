import subprocess


def test_start_proxy_accepts_non_interactive(tmp_path):
    # Call the CLI with --non-interactive; expect exit code 0 or non-fatal error-free handling
    result = subprocess.run([
        "python", "-m", "dockertree.cli", "start-proxy", "--non-interactive"
    ], capture_output=True, text=True)
    # Should not include 'No such option: --non-interactive'
    combined = (result.stdout or "") + (result.stderr or "")
    assert "No such option: --non-interactive" not in combined


def test_stop_proxy_accepts_non_interactive(tmp_path):
    result = subprocess.run([
        "python", "-m", "dockertree.cli", "stop-proxy", "--non-interactive"
    ], capture_output=True, text=True)
    combined = (result.stdout or "") + (result.stderr or "")
    assert "No such option: --non-interactive" not in combined

