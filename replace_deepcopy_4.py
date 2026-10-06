def replace_deepcopy_in_file(filepath):
    with open(filepath, 'r') as f:
        content = f.read()

    # Replacing copy.deepcopy with deepcopy where we know the object has a .copy()

    # We will search for all python/bionetgen/atomizer occurrences of deepcopy and see if they can use .copy()
    pass
