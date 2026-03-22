from pathlib import Path
from xml_to_usda.pipeline import load_canonical_model
from xml_to_usda.usda_writer import _render_joint_paths, _render_joint_basenames
p = Path(r'D:\3D Personal\VibeCode\XMLtoUSDAconverter\samples\speedtree\simple_tree\variants\SimpleTree_01.xml')
_, model, diagnostics = load_canonical_model(str(p))
print(_render_joint_basenames(model, root_joint_name='tmp_check'))
print(_render_joint_paths(model, root_joint_name='tmp_check'))
