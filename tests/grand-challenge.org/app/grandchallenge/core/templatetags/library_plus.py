from django import template


class LibraryPlus(template.Library):
    """
    Holds all registered template tags. Extends basic django tag functionality
    to pass an with extra 'usagestr' argument. This makes it possible to
    register additional info for the usage of a tag, which can be printed or
    shown to a user later on
    """

    def __init__(self):
        self.usagestrings = {}
        super().__init__()

    def tag(self, name=None, compile_function=None, usagestr=""):
        tagfunction = super().tag(name, compile_function)
        # fixme: Why is this function called twice for each @register.tag call in grandchallenge_tags.py?
        # Second call has no 'usagestr' defined workaround now is to check for
        # existing key and not overwriting it.
        if name not in self.usagestrings:
            self.usagestrings[name] = usagestr
        return tagfunction
