import types
from functools import update_wrapper
from pprint import pprint

import fastpt
from .util import flattener

class _obj(object):
    def __init__(self, **kw):
        for k,v in kw.iteritems():
            setattr(self,k,v)

class _Template(object):
    __methods__=()
    loader = None

    def __init__(self, context=None):
        if context is None: context = {}
        self._context = context
        self.__globals__ = dict(
            context,
            local=self,
            self=self,
            __builtins__=__builtins__,
            __fpt__=fastpt.v2)
        for k,v in self.__methods__:
            v = v.bind_instance(self)
            setattr(self, k, v)
            self.__globals__[k] = v
        self.__fpt__ = _obj(
            render=self._render,
            extend=self._extend,
            push_switch=self._push_switch,
            pop_switch=self._pop_switch,
            case=self._case,
            import_=self._import)
        self._switch_stack = []

    def __iter__(self):
        for chunk in self.__call__():
            yield unicode(chunk)

    def _render(self):
        return u''.join(self)

    def _extend(self, parent):
        if isinstance(parent, basestring):
            parent = self._import(parent)
        p_inst = parent(self._context)
        p_globals = p_inst.__globals__
        # Override methods from child
        for k,v in self.__methods__:
            if k == '__call__': continue
            p_globals[k] = getattr(self, k)
        p_globals['child'] = self
        p_globals['local'] = p_inst
        p_globals['self'] = self.__globals__['self']
        self.__globals__['parent'] = p_inst
        return p_inst

    def _push_switch(self, expr):
        self._switch_stack.append(expr)

    def _pop_switch(self):
        self._switch_stack.pop()

    def _case(self, obj):
        return obj == self._switch_stack[-1]

    def _import(self, name):
        return self.loader.import_(name)

def Template(ns):
    dct = {}
    methods = dct['__methods__'] = []
    for name in dir(ns):
        value = getattr(ns, name)
        if getattr(value, 'exposed', False):
            methods.append((name, TplFunc(value.im_func)))
    return type(ns.__name__,(_Template,), dct)

def from_ir(ir_node):
    from fastpt import v2 as fpt
    py_text = '\n'.join(map(str, ir_node.py()))
    dct = dict(fpt=fpt)
    exec py_text in dct
    tpl = dct['template']
    tpl.py_text = py_text
    return tpl

class TplFunc(object):

    def __init__(self, func, inst=None):
        self._func = func
        self._inst = inst
        self._bound_func = None

    def bind_instance(self, inst):
        return TplFunc(self._func, inst)

    def __repr__(self): # pragma no cover
        if self._inst:
            return '<bound tpl_function %r of %r>' % (
                self._func.func_name, self._inst)
        else:
            return '<unbound tpl_function %r>' % (self._func.func_name)

    def __call__(self, *args, **kwargs):
        if self._bound_func is None:
            self._bound_func = self._bind_globals(
                self._inst.__globals__)
        return self._bound_func(*args, **kwargs)

    def _bind_globals(self, globals):
        '''Return a function which has the globals dict set to 'globals' and which
        flattens the result of self._func'.
        '''
        func = types.FunctionType(
            self._func.func_code,
            globals,
            self._func.func_name,
            self._func.func_defaults,
            self._func.func_closure
            )
        return update_wrapper(
            lambda *a,**kw:flattener(func(*a,**kw)),
            func)
