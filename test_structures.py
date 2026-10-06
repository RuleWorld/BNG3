from bionetgen.atomizer.utils.structures import Species, Molecule, Component

s = Species()
s.molecules = [Molecule("M1"), Molecule("M2")]
s.molecules[0].components = [Component("c1")]
s.molecules[1].components = [Component("c2")]

s2 = s.copy()
print(s.molecules[0].components[0].name)
print(s2.molecules[0].components[0].name)
