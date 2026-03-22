from pathlib import Path
from xml_to_usda.pipeline import convert_file
p = Path(r'D:\3D Personal\XMLtoUSD_miscFiles\SkeletyalAssemblyTest_Spruce_Big_low_twoTrunkGenerators.xml')
out = Path(r'D:\3D Personal\VibeCode\XMLtoUSDAconverter\_tmp_check.usda')
r = convert_file(str(p), str(out))
print(r.output_path)
