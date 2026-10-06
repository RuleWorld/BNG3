import re

def replace_deepcopy_in_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Replacing deepcopy with .copy() for species, molecules, and components
    # where deepcopy is used.

    # We will just write a simple sed equivalent to do replacements where it is safe to use .copy()

    replacements = [
        ("deepcopy(translator[baseName])", "translator[baseName].copy()"),
        ("deepcopy(species)", "species.copy()"),
        ("deepcopy(tmpSpecies.molecules[0])", "tmpSpecies.molecules[0].copy()"),
        ("deepcopy(newComponent1)", "newComponent1.copy()"),
        ("deepcopy(newComponent2)", "newComponent2.copy()"),
        ("deepcopy(component)", "component.copy()"),
        ("deepcopy(newComponent)", "newComponent.copy()"),
        ("deepcopy(differenceParameter)", "copy.deepcopy(differenceParameter)"),
        ("deepcopy(ruleList)", "copy.deepcopy(ruleList)"),
        ("deepcopy(intersection)", "copy.deepcopy(intersection)"),
        ("deepcopy(tmp2)", "tmp2.copy()"),
        ("deepcopy(stmp)", "stmp.copy()"),
        ("deepcopy(tmp)", "tmp.copy()")
    ]

    for old, new in replacements:
        content = content.replace(old, new)

    with open(filepath, 'w') as f:
        f.write(content)

replace_deepcopy_in_file('python/bionetgen/atomizer/atomizer/moleculeCreation.py')
replace_deepcopy_in_file('python/bionetgen/atomizer/atomizer/analyzeSBML.py')
