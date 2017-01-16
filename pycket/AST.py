from pycket.util  import snake_case
from rpython.rlib import jit, objectmodel

class Visitable(type):
    def __new__(cls, name, bases, dct):
        visit_method_name = "visit_" + snake_case(name)
        @objectmodel.specialize.argtype(1)
        def dispatch_visitor(self, visitor, *args):
            method = getattr(visitor, visit_method_name)
            result = method(self, *args)
            return result
        if dct.get('visitable', False):
            dct['visit'] = dispatch_visitor
        result = type.__new__(cls, name, bases, dct)
        return result

class AST(object):
    __metaclass__ = Visitable

    _attrs_ = ["should_enter", "_mvars", "_fvars", "surrounding_lambda", "_stringrepr"]
    _immutable_fields_ = ["should_enter", "surrounding_lambda"]
    _settled_ = True

    should_enter = False # default value
    _stringrepr = None # default value
    _mvars = None
    _fvars = None
    surrounding_lambda = None

    simple = False
    ispure = False

    def defined_vars(self, defs):
        pass

    def interpret(self, env, cont):
        from pycket.interpreter import return_value_direct
        # default implementation for simple AST forms
        assert self.simple
        # interpret should only be called from interpret_one, therefore it's
        # safe to not use the Label implementation of return_value here
        return return_value_direct(self.interpret_simple(env), env, cont)

    def interpret_simple(self, env):
        raise NotImplementedError("abstract base class")

    def set_surrounding_lambda(self, lam):
        from pycket.interpreter import Lambda
        assert isinstance(lam, Lambda)
        self.surrounding_lambda = lam
        for child in self.direct_children():
            child.set_surrounding_lambda(lam)

    def set_should_enter(self):
        """ Set the should_enter field and returns whether or not the field was
        already set. This looks potentially dangerous: the field is marked
        immutable above. It works however, because should_enter MUST only be
        used for deciding whether to use can_enter_jit or not. As long as that
        is the case, mutating it without informing the JIT is fine: We don't
        want the existing JIT code to be thrown out just because we set a flag
        on an AST somewhere that was already traced. The interpreter is not
        affected and will see the change, thus potentially newly tracing the
        AST.
        """
        if not self.should_enter:
            self.should_enter = True
            return True
        return False

    def direct_children(self):
        return []

    def collect_module_info(self, info):
        return self.direct_children()

    def resultof(self):
        return self

    def free_vars(self):
        if self._fvars is None:
            self._fvars = self._free_vars()
        return self._fvars

    def _free_vars(self):
        from pycket.interpreter import SymbolSet
        free_vars = SymbolSet.EMPTY
        for child in self.direct_children():
            free_vars = free_vars.union(child.free_vars())
        return free_vars

    def assign_convert(self, vars, env_structure):
        """ make a copy of the AST that converts all writable variables into
        using cells. In addition, compute the state of the environment for
        every AST node that needs to know.

        The vars argument contains the variables that need to use cells.
        The env_structure is an instance of SymList (or None) describing the
        environment at that AST node.
        """
        raise NotImplementedError("abstract base class")

    def mutated_vars(self):
        if self._mvars is None:
            self._mvars = self._mutated_vars()
        return self._mvars

    def _mutated_vars(self):
        from pycket.interpreter import variable_set
        x = variable_set()
        children = self.direct_children()
        if not children:
            return variable_set()

        for b in self.direct_children():
            x.update(b.mutated_vars())
        return x

    def _clean_cache(self):
        self._mvars = None
        self._fvars = None

    def clean_caches(self):
        nodes = [self]
        while nodes:
            node = nodes.pop()
            node._clean_cache()
            nodes.extend(node.direct_children())

    def normalize(self, ctxt):
        return ctxt.plug(self)

    def tostring(self):
        _stringrepr = self._stringrepr
        if _stringrepr is None:
            _stringrepr = self._stringrepr = self._tostring()
        return _stringrepr

    def _tostring(self):
        return "UNKNOWN AST: "

    def __str__(self):
        return self.tostring()

