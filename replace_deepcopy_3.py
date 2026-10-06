def replace_deepcopy_in_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    replacements = [
        ("deepcopy(tmp)", "tmp[:]"), # tmp is a list here
        ("deepcopy(tmpCandidates)", "copy.deepcopy(tmpCandidates)"),
        ("deepcopy(dependencyGraph)", "copy.deepcopy(dependencyGraph)"),
        ("deepcopy(prunnedDependencyGraph)", "copy.deepcopy(prunnedDependencyGraph)"),
        ("deepcopy(graph)", "copy.deepcopy(graph)"),
    ]
    for old, new in replacements:
        content = content.replace(old, new)

    with open(filepath, 'w') as f:
        f.write(content)

replace_deepcopy_in_file('python/bionetgen/atomizer/atomizer/resolveSCT.py')
