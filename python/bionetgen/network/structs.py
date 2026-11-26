import re


class NetworkObj:
    """Base class for network items."""

    def __init__(self):
        self._comment = ""
        self._line_label = None

    def __str__(self) -> str:
        return self.gen_string()

    def __repr__(self) -> str:
        return self.gen_string()

    def __contains__(self, key):
        return hasattr(self, key)

    def __getitem__(self, key):
        return getattr(self, key)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __delitem__(self, key):
        delattr(self, key)

    @property
    def comment(self):
        return self._comment

    @comment.setter
    def comment(self, val):
        if val is not None:
            if len(val) > 0:
                self._comment = re.sub(r"^#+", "", val)
            else:
                self._comment = None
        else:
            self._comment = None

    @property
    def line_label(self):
        return self._line_label

    @line_label.setter
    def line_label(self, val):
        try:
            ll = int(val)
            self._line_label = "{} ".format(ll)
        except (TypeError, ValueError):
            self._line_label = "{}: ".format(val)

    def print_line(self) -> str:
        s = "  "
        if self.line_label is not None:
            s += self.line_label
        s += str(self)
        if self.comment is not None:
            s += " #{}".format(self.comment)
        return s

    def gen_string(self) -> str:
        raise NotImplementedError


class NetworkParameter(NetworkObj):
    def __init__(self, pid, name, value, comment=""):
        super().__init__()
        self.line_label = pid
        self.name = name
        self.value = value
        self.comment = comment

    def gen_string(self) -> str:
        return "{} {}".format(self.name, self.value)


class NetworkCompartment(NetworkObj):
    def __init__(self, name, dim, size, outside=None):
        super().__init__()
        self.name = name
        self.dim = dim
        self.size = size
        self.outside = outside

    def gen_string(self) -> str:
        s = "{} {} {}".format(self.name, self.dim, self.size)
        if self.outside is not None:
            s += " {}".format(self.outside)
        return s


class NetworkGroup(NetworkObj):
    def __init__(self, gid, name, members=[], comment=""):
        super().__init__()
        self.line_label = gid
        self.name = name
        self.members = members
        self.comment = comment

    def gen_string(self) -> str:
        return "{} {} ".format(self.name, ",".join(self.members))


class NetworkSpecies(NetworkObj):
    def __init__(self, sid, name, count=0, comment=""):
        super().__init__()
        self.line_label = sid
        self.name = name
        self.count = count
        self.comment = comment

    def gen_string(self) -> str:
        return "{} {}".format(self.name, self.count)


class NetworkFunction(NetworkObj):
    def __init__(self, name, expr, args=None):
        super().__init__()
        self.name = name
        self.expr = expr
        self.args = args

    def gen_string(self) -> str:
        if self.args is None:
            return "{} = {}".format(self.name, self.expr)
        return "{}({}) = {}".format(self.name, ",".join(self.args), self.expr)


class NetworkReaction(NetworkObj):
    def __init__(
        self, rid, reactants=[], products=[], rate_constant=None, comment=None
    ) -> None:
        super().__init__()
        self.line_label = rid
        self.reactants = reactants
        self.products = products
        self.rate_constant = rate_constant
        self.comment = comment

    def gen_string(self):
        react = ",".join(str(x) for x in self.reactants)
        prod = ",".join(str(x) for x in self.products)
        return "{} {} {}".format(react, prod, self.rate_constant)


class NetworkEnergyPattern(NetworkObj):
    def __init__(self, name, pattern, expression):
        super().__init__()
        self.name = name
        self.pattern = pattern
        self.expression = expression

    def gen_string(self) -> str:
        return "{} {}".format(self.pattern, self.expression)


class NetworkPopulationMap(NetworkObj):
    def __init__(self, name, struct_species, pop_species, rate):
        super().__init__()
        self.name = name
        self.struct_species = struct_species
        self.pop_species = pop_species
        self.rate = rate

    def gen_string(self) -> str:
        return "{} -> {} {}".format(self.struct_species, self.pop_species, self.rate)
