from bionetgen.network.networkparser import BNGNetworkParser
from bionetgen.core.exc import BNGModelError
from bionetgen.core.utils.logging import BNGLogger
from bionetgen.network.blocks import (
    NetworkGroupBlock,
    NetworkParameterBlock,
    NetworkReactionBlock,
    NetworkSpeciesBlock,
)

logger = BNGLogger()


class Network:
    """Compatibility network model object for .net files."""

    def __init__(self, bngl_model, BNGPATH=None):
        self.active_blocks = []
        self.block_order = ["parameters", "species", "reactions", "groups"]
        self.network_name = ""
        self.bngnetworkparser = BNGNetworkParser(bngl_model)
        self.bngnetworkparser.parse_network(self)
        for block in self.block_order:
            if block not in self.active_blocks:
                self.add_empty_block(block)
        if not self.active_blocks:
            raise BNGModelError(
                bngl_model,
                message="No active blocks. Please ensure model is in proper BNGL or BNG-XML format",
            )

    def __str__(self):
        model_str = ""
        for block in self.block_order:
            if hasattr(self, block):
                if len(getattr(self, block)) > 0:
                    if getattr(self, block).name not in self.active_blocks:
                        self.active_blocks.append(block)
                elif len(getattr(self, block)) == 0 and block in self.active_blocks:
                    self.active_blocks.remove(block)
            if block in self.active_blocks:
                if block != "actions" and len(getattr(self, block)) > 0:
                    model_str += str(getattr(self, block))
        return model_str

    def __repr__(self):
        return self.network_name

    def __iter__(self):
        active_ordered_blocks = [
            getattr(self, i) for i in self.block_order if i in self.active_blocks
        ]
        return active_ordered_blocks.__iter__()

    def add_block(self, block):
        block_adder = self._resolve_block_adder(block.name)
        block_adder(block)

    def add_empty_block(self, block_name):
        block_adder = self._resolve_block_adder(block_name)
        block_adder()

    def _resolve_block_adder(self, block_name):
        normalized_name = block_name.replace(" ", "_")
        block_adders = {
            "parameters": self.add_parameters_block,
            "species": self.add_species_block,
            "reactions": self.add_reactions_block,
            "groups": self.add_groups_block,
        }
        if normalized_name not in block_adders:
            supported_names = ", ".join(block_adders)
            raise ValueError(
                f"Unsupported block name '{block_name}'. Supported block names: {supported_names}"
            )
        return block_adders[normalized_name]

    def add_parameters_block(self, block=None):
        if block is not None:
            if not isinstance(block, NetworkParameterBlock):
                err_msg = "The given block is not a NetworkParameterBlock"
                logger.error(err_msg, loc=f"{__file__} : Network.add_parameters_block()")
                raise BNGModelError(self, message=err_msg)
            self.parameters = block
            if "parameters" not in self.active_blocks:
                self.active_blocks.append("parameters")
        else:
            self.parameters = NetworkParameterBlock()

    def add_species_block(self, block=None):
        if block is not None:
            if not isinstance(block, NetworkSpeciesBlock):
                err_msg = "The given block is not a NetworkSpeciesBlock"
                logger.error(err_msg, loc=f"{__file__} : Network.add_species_block()")
                raise BNGModelError(self, message=err_msg)
            self.species = block
            if "species" not in self.active_blocks:
                self.active_blocks.append("species")
        else:
            self.species = NetworkSpeciesBlock()

    def add_groups_block(self, block=None):
        if block is not None:
            if not isinstance(block, NetworkGroupBlock):
                err_msg = "The given block is not a NetworkGroupBlock"
                logger.error(err_msg, loc=f"{__file__} : Network.add_groups_block()")
                raise BNGModelError(self, message=err_msg)
            self.groups = block
            if "groups" not in self.active_blocks:
                self.active_blocks.append("groups")
        else:
            self.groups = NetworkGroupBlock()

    def add_reactions_block(self, block=None):
        if block is not None:
            if not isinstance(block, NetworkReactionBlock):
                err_msg = "The given block is not a NetworkReactionBlock"
                logger.error(err_msg, loc=f"{__file__} : Network.add_reactions_block()")
                raise BNGModelError(self, message=err_msg)
            self.reactions = block
            if "reactions" not in self.active_blocks:
                self.active_blocks.append("reactions")
        else:
            self.reactions = NetworkReactionBlock()

    def write_model(self, file_name):
        with open(file_name, "w") as f:
            f.write("".join(str(getattr(self, block)) for block in self.active_blocks))
