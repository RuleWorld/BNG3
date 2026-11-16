try:
    from typing import OrderedDict
except ImportError:
    from collections import OrderedDict

import keyword

from bionetgen.core.utils.logging import BNGLogger

from .structs import (
    NetworkCompartment,
    NetworkEnergyPattern,
    NetworkFunction,
    NetworkGroup,
    NetworkParameter,
    NetworkPopulationMap,
    NetworkReaction,
    NetworkSpecies,
)

logger = BNGLogger()


class NetworkBlock:
    def __init__(self) -> None:
        self.name = "NetworkBlock"
        self.comment = (None, None)
        self._changes = OrderedDict()
        self.items = OrderedDict()
        self._recompile = False

    def __str__(self) -> str:
        return self.gen_string()

    def __len__(self) -> int:
        return len(self.items)

    def __repr__(self) -> str:
        return "{} block with {} item(s): {}".format(
            self.name, len(self.items), list([i.name for i in self.items.values() if hasattr(i, 'name')])
        )

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.items.keys())[key]
        return self.items[key]

    def __setitem__(self, key, value) -> None:
        self.items[key] = value

    def __delitem__(self, key) -> None:
        self.items.pop(key)

    def __iter__(self):
        return self.items.keys().__iter__()

    def __contains__(self, key) -> bool:
        return key in self.items

    def __setattr__(self, name, value) -> None:
        changed = False
        if hasattr(self, "items") and name in self.items.keys():
            try:
                new_value = float(value)
            except (TypeError, ValueError):
                self.items[name] = value
            else:
                changed = True
                self.items[name] = new_value
            if changed:
                self._changes[name] = new_value
                self.__dict__[name] = new_value
        else:
            self.__dict__[name] = value

    def gen_string(self) -> str:
        if self.comment[0] is not None:
            block_lines = ["\nbegin {} #{}".format(self.name, self.comment[0])]
        else:
            block_lines = ["\nbegin {}".format(self.name)]
        for item in self.items.keys():
            block_lines.append(self.items[item].print_line())
        if self.comment[1] is not None:
            block_lines.append("end {} #{}\n".format(self.name, self.comment[1]))
        else:
            block_lines.append("end {}\n".format(self.name))
        return "\n".join(block_lines)

    def add_item(self, item_tpl) -> None:
        name, value = item_tpl
        if name is None:
            name = len(self.items)
        self.items[name] = value
        set_attr = False
        if isinstance(name, str) and name.isidentifier() and not keyword.iskeyword(name):
            if not hasattr(self.__class__, name) and name not in [
                "name", "items", "comment", "_changes", "_recompile",
            ]:
                set_attr = True
        if set_attr:
            try:
                setattr(self, name, value)
            except Exception as exc:
                logger.warning(
                    f"Unable to bind attribute {name!r} for the {self.name} block",
                    loc=f"{__file__} : NetworkBlock.add_item()",
                )
        self._recompile = True

    def add_items(self, item_list) -> None:
        for item in item_list:
            self.add_item(item)


class NetworkParameterBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "parameters"

    def add_parameter(self, *args, **kwargs) -> None:
        p = NetworkParameter(*args, **kwargs)
        self.add_item((p.name, p))


class NetworkCompartmentBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "compartments"

    def add_compartment(self, *args, **kwargs) -> None:
        c = NetworkCompartment(*args, **kwargs)
        self.add_item((c.name, c))


class NetworkGroupBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "groups"

    def add_group(self, *args, **kwargs) -> None:
        g = NetworkGroup(*args, **kwargs)
        key = g.name if hasattr(g, 'name') else args[1]
        self.add_item((key, g))


class NetworkSpeciesBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "species"

    def add_species(self, *args, **kwargs) -> None:
        s = NetworkSpecies(*args, **kwargs)
        key = getattr(s, 'line_label', None)
        if key is None and args:
            key = args[0]
        self.add_item((key, s))


class NetworkFunctionBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "functions"

    def add_function(self, *args, **kwargs) -> None:
        f = NetworkFunction(*args, **kwargs)
        self.add_item((f.name, f))


class NetworkReactionBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "reactions"

    def add_reaction(self, *args, **kwargs) -> None:
        r = NetworkReaction(*args, **kwargs)
        key = getattr(r, 'line_label', None)
        if key is None and args:
            key = args[0]
        self.add_item((key, r))


class NetworkEnergyPatternBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "energy patterns"

    def add_energy_pattern(self, *args, **kwargs) -> None:
        e = NetworkEnergyPattern(*args, **kwargs)
        key = getattr(e, 'line_label', None)
        if key is None and args:
            key = args[0]
        self.add_item((key, e))


class NetworkPopulationMapBlock(NetworkBlock):
    def __init__(self) -> None:
        super().__init__()
        self.name = "population maps"

    def add_population_map(self, *args, **kwargs) -> None:
        p = NetworkPopulationMap(*args, **kwargs)
        key = getattr(p, 'line_label', None)
        if key is None and args:
            key = args[0]
        self.add_item((key, p))
