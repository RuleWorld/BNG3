from sympy import Function


class sympyPiece(Function):
    nargs = (3, 4, 5)


class sympyIF(Function):
    nargs = 3


class sympyGT(Function):
    nargs = 2


class sympyLT(Function):
    nargs = 2


class sympyGEQ(Function):
    nargs = 2


class sympyLEQ(Function):
    nargs = 2


class sympyAnd(Function):
    nargs = (2, 3, 4, 5)


class sympyOr(Function):
    nargs = (2, 3, 4, 5)


class sympyNot(Function):
    nargs = 1
