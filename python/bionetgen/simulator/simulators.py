from .librrsimulator import libRRSimulator


def sim_getter(model_file=None, model_str=None, sim_type="libRR"):
    """
    Convenience function to get a simulator object of a specific type.
    Allows you to pull a simulator object given a model file path.

    Note: This likely needs to be refactored but for now it works.

    Parameters
    ----------
    model_file : str, optional
        The path to the model file, at the moment only BNGL is expected
        but this can change in the future.
    model_str : str, optional
        Instead of the path to the model you can also supply the model
        string instead.
    sim_type : str, optional
        The name of the type of simulator object to get. At the moment only
        libRoadRunner is allowed, allowed value is "libRR".

    Returns
    -------
    BNGSimulator
        A simulator object with an API that's supposed to be agnostic to the
        underlying simulator it's running.
    """
    if model_file is None and model_str is None:
        raise ValueError("Provide model_file or model_str")
    if not isinstance(sim_type, str):
        raise TypeError("sim_type must be a string")

    normalized_type = sim_type.lower()
    if normalized_type == "cpy":
        raise ValueError("Simulator type 'cpy' is no longer supported")
    if normalized_type != "librr":
        raise ValueError(f"Simulator type {sim_type!r} not supported")

    if model_str is not None and model_file is None:
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w+") as model_file_obj:
            model_file_obj.write(model_str)
            model_file = model_file_obj.name
            # Need to go back to beginning for callers that inspect the file.
            model_file_obj.seek(0)
            return libRRSimulator(model_file=model_file)

    return libRRSimulator(model_file=model_file)
