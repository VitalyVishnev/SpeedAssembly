"""Copy the UE 5.7 Asset Action command to the system clipboard."""

from pathlib import Path
import subprocess


source = Path(__file__).with_name("ue57_fix_selected_foliage_bones.py").read_text(
    encoding="utf-8"
)
command = f"exec({source!r})"

try:
    subprocess.run("clip", input=command, text=True, check=True, shell=True)
except Exception:
    print(command)
