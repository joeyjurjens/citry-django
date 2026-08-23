from wagtail import hooks

from testproject import blocks


@hooks.register("register_components")
def register_demo_components():
    return [blocks.AccordionBlock, blocks.AccordionItemBlock]
