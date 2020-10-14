from abc import ABC, abstractmethod
import math
import pdb
import collections
import itertools
import tensorflow.compat.v1 as tf

from instruction import *
from primitives import Line, Point, Circle, Num
from util import is_number, FuncInfo


# Also stores the points used to compute it
LineSF = collections.namedtuple("LineSF", ["a", "b", "c", "p1", "p2"])

CircleNF = collections.namedtuple("CircleNF", ["center", "radius"])

# by convention, n is a unit vector located in the upper-half plane
LineNF = collections.namedtuple("LineNF", ["n", "r"])




class Optimizer(ABC):
    def __init__(self, instructions, opts):

        self.losses = dict()
        self.has_loss = False
        self.opts = opts
        self.verbosity = opts['verbosity']
        self.instructions = instructions
        self.ndgs = dict()
        self.goals = dict()

        self.all_points = list()

        self.name2pt = dict()
        self.name2line = dict()
        self.name2circ = dict()

        self.segments = list()
        self.unnamed_points = list()
        self.unnamed_lines = list()
        self.unnamed_circles = list()

        super().__init__()

    def preprocess(self):
        for i in self.instructions:
            self.process_instruction(i)

    def process_instruction(self, i):

        if isinstance(i, Sample):
            self.sample(i)
        elif isinstance(i, Compute):
            self.compute(i)
        elif isinstance(i, Parameterize):
            self.parameterize(i)
        elif isinstance(i, Assert):
            self.add(i)
        elif isinstance(i, AssertNDG):
            self.addNDG(i)
        elif isinstance(i, Confirm):
            self.confirm(i)
        else:
            raise NotImplementedError("FIXME: Finish process_instruction")

    @abstractmethod
    def get_point(self, x, y):
        pass

    @abstractmethod
    def simplify(self, p, method="all"):
        pass

    def lookup_pt(self, p, name=None):
        if isinstance(p.val, str): # Base case
            return self.name2pt[p]

        if isinstance(p.val, FuncInfo):
            head, args = p.val
            if head == "__val__":
                return args[0]
            elif head == "midp": return self.midp(*self.lookup_pts(args))
            elif head == "circumcenter": return self.circumcenter(*self.lookup_pts(args))
            elif head == "orthocenter": return self.orthocenter(*self.lookup_pts(args))
            elif head == "incenter": return self.incenter(*self.lookup_pts(args))
            elif head == "centroid": return self.centroid(*self.lookup_pts(args))
            elif head == "amidpOpp": return self.amidp_opp(*self.lookup_pts(args))
            elif head == "amidpSame": return self.amidp_same(*self.lookup_pts(args))
            elif head == "excenter": return self.excenter(*self.lookup_pts(args))
            elif head == "foot":
                X, A, B = args
                foot_p = Point(FuncInfo("interLL", [Line(FuncInfo("connecting", [A, B])),
                                                    Line(FuncInfo("perpAt", [X, A, B]))]))
                return self.lookup_pt(foot_p)
            elif head == "harmonicLConj": return self.harmonic_l_conj(*self.lookup_pts(args))
            elif head == "origin":
                assert(len(args) == 1)
                circ = args[0]
                cnf = self.circ2nf(circ)
                return cnf.center
            elif head == "interLL":
                l1, l2 = args
                lnf1 = self.line2nf(l1)
                lnf2 = self.line2nf(l2)
                return self.inter_ll(lnf1, lnf2)
            elif head == "interLC":
                l, c, root_select = args
                lnf = self.line2nf(l)
                cnf = self.circ2nf(c)
                if name:
                    self.make_lc_intersect(name, lnf, cnf)
                else:
                    # Use random name as point is unnamed, but we still want to force LC to intersect
                    rand_name = get_random_string(6)
                    self.make_lc_intersect(rand_name, lnf, cnf)
                return self.inter_lc(lnf, cnf, root_select)
            elif head == "interCC":
                c1, c2, root_select = args
                cnf1 = self.circ2nf(c1)
                cnf2 = self.circ2nf(c2)
                if name:
                    self.make_lc_intersect(name, self.radical_axis(cnf1, cnf2), cnf1)
                else:
                    # Use random name as point is unnamed, but we still want to force LC to intersect
                    rand_name = get_random_string(6)
                    self.make_lc_intersect(rand_name, self.radical_axis(cnf1, cnf2), cnf1)
                return self.inter_cc(cnf1, cnf2, root_select)
            elif head == "isogonal": return self.isogonal(*self.lookup_pts(args))
            elif head == "isotomic": return self.isotomic(*self.lookup_pts(args))
            elif head == "inverse": return self.inverse(*self.lookup_pts(args))
            elif head == "reflectPL":
                if len(args) == 3:
                    # reflection of X over line AB
                    X, A, B = args
                elif len(args) == 2:
                    X, l = args
                    lnf = self.line2nf(l)
                    p1, p2 = self.lnf2pp(lnf)
                    A = Point(FuncInfo("__val__", [p1]))
                    B = Point(FuncInfo("__val__", [p2]))
                else:
                    raise RuntimeError("invalid reflectPL")
                p_val = Point(FuncInfo("interLC", [
                    Line(FuncInfo("perpAt", [X, A, B])),
                    Circle(FuncInfo("coa", [A, X])),
                    Root("neq", [X])
                ]))
                return self.lookup_pt(p_val)
            elif head == "midpFrom": return self.midp_from(*self.lookup_pts(args))
            elif head == "mixtilinearIncenter": return self.mixtilinear_incenter(*self.lookup_pts(args))

            else:
                raise NotImplementedError(f"[lookup_pt] Unsupported head {head}")
        else:
            raise RuntimeError("Invalid point type")

    def lookup_pts(self, ps):
        p_vals = list()
        for p in ps:
            p_vals.append(self.lookup_pt(p))
        return p_vals

    def eval_num(self, n_info):
        n_val = n_info.val
        if not isinstance(n_val, tuple) and is_number(n_val):
            return self.const(n_val)

        n_pred = n_val[0]
        n_args = n_val[1]

        if n_pred == "dist":
            p1, p2 = self.lookup_pts(n_args)
            return self.dist(p1, p2)
        elif n_pred == "uangle":
            p1, p2, p3 = self.lookup_pts(n_args)
            return self.angle(p1, p2, p3)
        elif n_pred == "area":
            p1, p2, p3 = self.lookup_pts(n_args)
            return self.area(p1, p2, p3)
        elif n_pred == "radius":
            circ = self.circ2nf(n_args[0])
            return circ.radius
        elif n_pred == "diam":
            circ = self.circ2nf(n_args[0])
            return 2 * circ.radius
        elif n_pred in ["div", "add", "mul", "sub", "pow"]:
            n1, n2 = [self.eval_num(n) for n in n_args]
            if n_pred == "div":
                return n1 / n2
            elif n_pred == "add":
                return n1 + n2
            elif n_pred == "mul":
                return n1 * n2
            elif n_pred == "sub":
                return n1 - n2
            else: # pow
                return n1 ** n2
        elif n_pred == "neg":
            n = self.eval_num(n_args[0])
            return -n
        elif n_pred == "sqrt":
            n = self.eval_num(n_args[0])
            return self.sqrt(n)
        else:
            raise NotImplementedError(f"[eval_num] Unsupported pred {n_pred}")

    @abstractmethod
    def mkvar(self, name, shape=[], lo=-1.0, hi=1.0, trainable=None):
        pass

    @abstractmethod
    def register_pt(self, p, P, save_name=True):
        pass

    @abstractmethod
    def register_line(self, l, L):
        pass

    @abstractmethod
    def register_circ(self, c, C):
        pass

    @abstractmethod
    def register_loss(self, key, var, weight=1.0):
        pass

    @abstractmethod
    def register_ndg(self, key, var, weight=1.0):
        pass

    @abstractmethod
    def register_goal(self, key, var):
        pass

    @abstractmethod
    def regularize_points(self):
        pass

    @abstractmethod
    def make_points_distinct(self):
        pass

    # FIXME: The below should be combined with an abstract Point class

    #####################
    ## Math Utilities
    ####################
    @abstractmethod
    def sum(self, xs):
        pass

    @abstractmethod
    def sqrt(self, x):
        pass

    @abstractmethod
    def sin(self, x):
        pass

    @abstractmethod
    def cos(self, x):
        pass

    @abstractmethod
    def asin(self, x):
        pass

    @abstractmethod
    def acos(self, x):
        pass

    @abstractmethod
    def tanh(self, x):
        pass

    @abstractmethod
    def sigmoid(self, x):
        pass

    @abstractmethod
    def const(self, x):
        pass

    @abstractmethod
    def max(self, x, y):
        pass

    @abstractmethod
    def min(self, x, y):
        pass

    @abstractmethod
    def cond(self, cond, t_lam, f_lam):
        pass

    @abstractmethod
    def lt(self, x, y):
        pass

    @abstractmethod
    def lte(self, x, y):
        pass

    @abstractmethod
    def gt(self, x, y):
        pass

    @abstractmethod
    def gte(self, x, y):
        pass

    @abstractmethod
    def eq(self, x, y):
        pass

    @abstractmethod
    def logical_or(self, x, y):
        pass

    @abstractmethod
    def abs(self, x):
        pass

    @abstractmethod
    def exp(self, x):
        pass

    def softmax(self, xs):
        exps = [self.exp(x) for x in xs]
        sum_exps = self.sum(exps)
        return [e / sum_exps for e in exps]

    #####################
    ## Sample
    ####################

    def sample(self, i):
        s_method = i.sampler
        s_args = i.args
        if s_method == "acuteIsoTri": self.sample_triangle(i.points, iso=s_args[0], acute=True)
        elif s_method == "acuteTri": self.sample_triangle(i.points, acute=True)
        elif s_method == "equiTri": self.sample_triangle(i.points, equi=True)
        elif s_method == "isoTri": self.sample_triangle(i.points, iso=s_args[0])
        elif s_method == "polygon": self.sample_polygon(i.points)
        elif s_method == "rightTri": self.sample_triangle(i.points, right=s_args[0])
        elif s_method == "triangle": self.sample_triangle(i.points)
        else: raise NotImplementedError(f"[sample] NYI: Sampling method {s_method}")

    def sample_uniform(self, p, lo=-1.0, hi=1.0, save_name=True):
        P   = self.get_point(x=self.mkvar(str(p)+"x", lo=lo, hi=hi),
                             y=self.mkvar(str(p)+"y", lo=lo, hi=hi))
        self.register_pt(p, P, save_name=save_name)
        return P


    def sample_polygon(self, ps):
        if len(ps) < 4:
            if self.verbosity > 0:
                print("WARNING: sample_polygon expecting >3 points")

        angle_zs = [self.mkvar(name=f"polygon_angle_zs_{i}", lo=-2.0, hi=2.0) for i in range(len(ps))]
        multiplicand = ((len(ps) - 2) / len(ps)) * math.pi
        angles = [multiplicand + (math.pi / 3) * self.tanh(0.2 * az) for az in angle_zs]

        scale_zs = [self.mkvar(name=f"polygon_scale_zs_{i}", lo=-2.0, hi=2.0) for i in range(len(ps))]
        scales = [0.5 * self.tanh(0.2 * sz) for sz in scale_zs]

        Ps = [self.get_point(self.const(-2.0), self.const(0.0)),
              self.get_point(self.const(2.0), self.const(0.0))]
        s = self.dist(Ps[0], Ps[1])

        for i in range(2, len(ps) + 1):
            # print(f"sampling polygon point: {i}")
            A, B = Ps[-2:]
            X = B + self.rotate_counterclockwise(-angles[i-1], A - B)
            P = B + (X - B).smul(s * (1 + scales[i-1]) / self.dist(X, B))
            # Ps.append(P)
            Ps.append(self.simplify(P, method="trig"))

        # Angles should sum to (n-2) * pi
        angle_sum = self.sum(angles)
        expected_angle_sum = math.pi * (len(ps) - 2)
        self.register_loss("polygon-angle-sum", angle_sum - expected_angle_sum, weight=1e-1)

        # First point shoudl equal the last point
        self.register_loss("polygon-first-eq-last", self.dist(Ps[0], Ps[len(ps)]), weight=1e-2)

        # First angle should be the one sampled (known to be <180)
        self.register_loss("polygon-first-angle-eq-sampled",
                           angles[0] - self.angle(Ps[-1], Ps[0], Ps[1]),
                           weight=1e-2)

        # for i in range(len(ps)):
            # self.segments.append((Ps[i], Ps[(i+1) % (len(ps))]))

        for p, P in zip(ps, Ps[:-1]):
            self.register_pt(p, P)


    def sample_triangle(self, ps, iso=None, right=None, acute=False, equi=False):
        if not (iso or right or acute or equi):
            return self.sample_polygon(ps)

        [nA, nB, nC] = ps
        B = self.get_point(self.const(-2.0), self.const(0.0))
        C = self.get_point(self.const(2.0), self.const(0.0))

        if iso is not None or equi:
            Ax = self.const(0)
        else:
            Ax = self.mkvar("tri_x", lo=-1.2, hi=1.2, trainable=False)

        if right is not None:
            Ay = self.sqrt(4 - (Ax ** 2))
        elif equi:
            Ay = 2 * self.sqrt(self.const(3.0))
        else:
            AyLo = 1.1 if acute else 0.4
            z = self.mkvar("tri")
            Ay = self.const(AyLo) + 3.0 * self.sigmoid(z)

        A = self.get_point(Ax, Ay)

        # Shuffle if the isosceles vertex was not C
        if iso == nB or right == nB:
            (A, B, C) = (B, A, C)
        elif iso == nC or right == nC:
            (A, B, C) = (C, B, A)

        self.register_pt(nA, A)
        self.register_pt(nB, B)
        self.register_pt(nC, C)

        self.segments.extend([(A, B), (B, C), (C, A)])

    #####################
    ## Compute
    ####################

    def compute(self, i):
        obj_name = i.obj_name
        c_method = i.computation.val[0]
        c_args = i.computation.val
        if isinstance(i.computation, Point):
            P = self.lookup_pt(i.computation, str(obj_name))
            self.register_pt(obj_name, P)

            # Add drawings
            """
            if c_method == "midp":
                A, B = self.lookup_pts(c_args[1])
                self.segments.append((A, B))
            elif c_method == "midpFrom":
                M, A = self.lookup_pts(c_args[1])
                self.segments.append((P, A))
            elif c_method == "circumcenter":
                A, _, _ = self.lookup_pts(c_args[1])
                # self.unnamed_circles.append((P, self.dist(P, A))) # P is the circumcenter
            elif c_method == "incenter":
                A, B, C = self.lookup_pts(c_args[1])
                # self.unnamed_circles.append((P, self.inradius(A, B, C))) # P is the incenter
            elif c_method == "excenter":
                A, B, C = self.lookup_pts(c_args[1])
                # self.unnamed_circles.append((P, self.exradius(A, B, C))) # P is the excenter
            elif c_method == "mixtilinearIncenter":
                A, B, C = self.lookup_pts(c_args[1])
                # self.unnamed_circles.append((P, self.mixtilinear_inradius(A, B, C))) # P is the mixtilinearIncenter
            elif c_method == "inverse":
                X, O, A = self.lookup_pts(c_args[1])
                # self.unnamed_circles.append((O, self.dist(O, A)))
            elif c_method == "harmonicLConj":
                X, A, B = self.lookup_pts(ps)
                self.segments.append((A, B))
                self.segments.append((X, P))
            """
        elif isinstance(i.computation, Line):
            L = self.line2nf(i.computation)
            self.register_line(obj_name, L)
        elif isinstance(i.computation, Circle):
            C = self.circ2nf(i.computation)
            self.register_circ(obj_name, C)
        else:
            raise NotImplementedError(f"[compute] NYI: {c_method} not supported")


    #####################
    ## Parameterize
    ####################

    def parameterize(self, i):
        p_name = i.obj_name
        p_method = i.parameterization[0]
        p_args = i.parameterization
        param_method = i.parameterization
        if p_method == "coords": self.parameterize_coords(p_name)
        elif p_method == "inPoly": self.parameterize_in_poly(p_name, p_args[1])
        elif p_method == "onCirc": self.parameterize_on_circ(p_name, p_args[1])
        elif p_method == "onLine": self.parameterize_on_line(p_name, p_args[1])
        elif p_method == "onRay": self.parameterize_on_ray(p_name, p_args[1])
        elif p_method == "onRayOpp": self.parameterize_on_ray_opp(p_name, p_args[1])
        elif p_method == "onSeg": self.parameterize_on_seg(p_name, p_args[1])
        elif p_method == "line": self.parameterize_line(p_name)
        elif p_method == "throughL": self.parameterize_line_through(p_name, p_args[1])
        elif p_method == "tangentLC": self.parameterize_line_tangentC(p_name, p_args[1])
        elif p_method == "tangentCC": self.parameterize_circ_tangentC(p_name, p_args[1])
        elif p_method == "throughC": self.parameterize_circ_through(p_name, p_args[1])
        elif p_method == "circle": self.parameterize_circ(p_name)
        elif p_method == "origin": self.parameterize_circ_centered_at(p_name, p_args[1])
        elif p_method == "radius": self.parameterize_circ_with_radius(p_name, p_args[1])
        else: raise NotImplementedError(f"FIXME: Finish parameterize: {i}")

    def parameterize_coords(self, p):
        return self.sample_uniform(p)

    def parameterize_line(self, l):
        p1 = Point(l.val + "_p1")
        p2 = Point(l.val + "_p2")

        P1 = self.sample_uniform(p1, save_name=False)
        P2 = self.sample_uniform(p2, save_name=False)

        return self.register_line(l, self.pp2lnf(P1, P2))

    def parameterize_line_through(self, l, ps):
        [through_p] = ps
        through_p = self.lookup_pt(through_p)

        p2 = Point(l.val + "_p2")
        P2 = self.sample_uniform(p2, save_name=False)

        return self.register_line(l, self.pp2lnf(through_p, P2))

    def parameterize_line_tangentC(self, l, args):
        [c] = args

        P1 = self.parameterize_on_circ(Point(f"{l.val}_p1"), [c], save_name=False)
        P1 = Point(FuncInfo('__val__', [P1]))
        L = self.line2nf(Line(FuncInfo("perpAt", [P1, Point(FuncInfo("origin", [c])), P1])))

        return self.register_line(l, L)


    def parameterize_circ(self, c):
        o = Point(c.val + "_origin")
        O = self.sample_uniform(o, save_name=False)
        circ_nf = CircleNF(center=O, radius=self.mkvar(name=f"{c.val}_origin", lo=0.25, hi=3.0))
        return self.register_circ(c, circ_nf)

    def parameterize_circ_centered_at(self, c, ps):
        [origin] = ps
        origin = self.lookup_pt(origin)
        circ_nf = CircleNF(center=origin, radius=self.mkvar(name=f"{c.val}_origin", lo=0.25, hi=3.0))
        return self.register_circ(c, circ_nf)

    def parameterize_circ_through(self, c, ps):
        [through_p] = ps
        through_p = self.lookup_pt(through_p)

        o = Point(c.val + "_origin")
        O = self.sample_uniform(o, save_name=False)

        radius = self.dist(through_p, O)
        circ_nf = CircleNF(center=O, radius=radius)
        return self.register_circ(c, circ_nf)

    def parameterize_circ_with_radius(self, c, rs):
        [radius] = rs
        radius = self.eval_num(radius)

        o = Point(c.val + "_origin")
        O = self.sample_uniform(o, save_name=False)

        circ_nf = CircleNF(center=O, radius=radius)
        return self.register_circ(c, circ_nf)

    def parameterize_circ_tangentC(self, c, args):
        [circ2] = args

        interP = self.parameterize_on_circ(Point(f"{c.val}_{circ2.val}_tangency"), [circ2], save_name=False)
        interP = Point(FuncInfo('__val__', [interP]))

        O = self.parameterize_on_line(Point(f"{c.val}_origin"),
                                      [Line(FuncInfo("connecting",
                                                     [interP, Point(FuncInfo("origin", [circ2]))]))],
                                      save_name=False)

        C = CircleNF(center=O, radius=self.dist(O, interP.val.args[0]))
        return self.register_circ(c, C)



    def parameterize_on_seg(self, p, ps):
        A, B = self.lookup_pts(ps)
        z = self.mkvar(name=f"{p}_seg")
        z = 0.2 * z
        self.register_loss(f"{p}_seg_regularization", z, weight=1e-4)
        # self.segments.append((A, B))
        return self.register_pt(p, A + (B - A).smul(self.sigmoid(z)))


    def parameterize_on_line(self, p, p_args, save_name=True):
        [l] = p_args
        # A, B = self.line2twoPts(l)
        A, B = self.lnf2pp(self.line2nf(l))
        z = self.mkvar(name=f"{p}_line")
        z = 0.2 * z
        self.register_loss(f"{p}_line_regularization", z, weight=1e-4)
        # TODO: arbitrary and awkward. Better to sample "zones" first?
        s = 3.0
        P1 = A + (A - B).smul(s)
        P2 = B + (B - A).smul(s)
        # self.segments.append((A, B))
        return self.register_pt(p, P1 + (P2 - P1).smul(self.sigmoid(z)), save_name=save_name)


    def parameterize_on_ray(self, p, ps):
        A, B = self.lookup_pts(ps)
        z = self.mkvar(name=f"{p}_ray", hi=2.0)
        P = A + (B - A).smul(self.exp(z))
        self.segments.extend([(A, B), (A, P)])
        return self.register_pt(p, P)


    def parameterize_on_ray_opp(self, p, ps):
        A, B = self.lookup_pts(ps)
        z = self.mkvar(f"{p}_ray_opp")
        P = A + (A - B).smul(self.exp(z))
        self.segments.extend([(A, B), (A, P)])
        return self.register_pt(p, P)


    def parameterize_on_circ(self, p, p_args, save_name=True):
        [circ] = p_args
        O, r = self.circ2nf(circ)
        rot = self.mkvar(name=f"{p}_rot")
        theta = rot * 2 * self.const(math.pi)
        X = self.get_point(x=O.x + r * self.cos(theta), y=O.y + r * self.sin(theta))
        return self.register_pt(p, X, save_name=save_name)
        # self.unnamed_circles.append((O, r))

    def parameterize_in_poly(self, p, ps):
        Ps = self.lookup_pts(ps)
        zs = [self.mkvar(name=f"{p}_in_poly_{poly_p}") for poly_p in ps]
        ws = self.softmax(zs)
        Px = self.sum([P.x * w for (P, w) in zip(Ps, ws)])
        Py = self.sum([P.y * w for (P, w) in zip(Ps, ws)])
        P = self.get_point(Px, Py)
        return self.register_pt(p, P)

    #####################
    ## Assert
    ####################

    def add(self, assertion):
        self.has_loss = True
        cons = assertion.constraint
        pred, args, negate = cons.pred, cons.args, cons.negate

        if negate:
            raise RuntimeError("[add] Mishandled negation")

        vals = self.assertion_vals(pred, args)

        a_str = f"{pred}_{'_'.join([str(a) for a in args])}"
        weight = 1 / len(vals)
        for i, val in enumerate(vals):
            loss_str = a_str if len(vals) == 1 else f"{a_str}_{i}"
            self.register_loss(loss_str, val, weight=weight)

    def addNDG(self, ndg):
        self.has_loss = True
        ndg_cons = ndg.constraint
        pred, args = ndg_cons.pred, ndg_cons.args

        vals = self.assertion_vals(pred, args)

        a_str = f"not_{pred}_{'_'.join([str(a) for a in args])}"
        weight = 1 / len(vals)

        for i, val in enumerate(vals):
            ndg_str = a_str if len(vals) == 1 else f"{a_str}_{i}"
            self.register_ndg(ndg_str, val, weight=weight)

    def confirm(self, goal):
        goal_cons = goal.constraint
        pred, args, negate = goal_cons.pred, goal_cons.args, goal_cons.negate

        vals = self.assertion_vals(pred, args)
        g_str = f"{pred}_{'_'.join([str(a) for a in args])}"
        if negate:
            if self.verbosity > 0:
                print("WARNING: Satisfied NDG goals will have non-zero values")
            g_str = f"not_{g_str}"

        for i, val in enumerate(vals):
            goal_str = g_str if len(vals) == 1 else f"{g_str}_{i}"
            self.register_goal(goal_str, val)

    def assertion_vals(self, pred, args):
        if pred == "amidpOpp":
            M, B, C, A = self.lookup_pts(args)
            return [self.dist(M, self.amidp_opp(B, C, A))]
        elif pred == "amidpSame":
            M, B, C, A = self.lookup_pts(args)
            return [self.dist(M, self.amidp_same(B, C, A))]
        elif pred == "between": return self.between_gap(*self.lookup_pts(args))
        elif pred == "circumcenter":
            O, A, B, C = self.lookup_pts(args)
            # self.unnamed_circles.append((O, self.dist(O, A)))
            return [self.dist(O, self.circumcenter(A, B, C))]
        elif pred == "coll":
            coll_args = self.lookup_pts(args)
            diffs = [self.coll_phi(A, B, C) for A, B, C in itertools.combinations(coll_args, 3)]
            # for i in range(len(coll_args)-1):
                # self.segments.append((coll_args[i], coll_args[i+1]))
            return diffs
        elif pred == "concur":
            l1, l2, l3 = args
            inter_12 = Point(FuncInfo("interLL", [l1, l2]))
            return self.assertion_vals("onLine", [inter_12, l3])
        elif pred == "cong":
            A, B, C, D = self.lookup_pts(args)
            # if A in [C, D]: self.unnamed_circles.append((A, self.dist(A, B)))
            # elif B in [C, D]: self.unnamed_circles.append((B, self.dist(A, B)))
            return [self.cong_diff(A, B, C, D)]
        elif pred == "contri":
            [A, B, C, P, Q, R] = self.lookup_pts(args)
            self.segments.extend([(A, B), (B, C), (C, A), (P, Q), (Q, R), (R, P)])
            return [self.eqangle6_diff(A, B, C, P, Q, R),
                    self.eqangle6_diff(B, C, A, Q, R, P),
                    self.eqangle6_diff(C, A, B, R, P, Q),
                    self.cong_diff(A, B, P, Q),
                    self.cong_diff(A, C, P, R),
                    self.cong_diff(B, C, Q, R)]
        elif pred == "cycl":
            cycl_args = self.lookup_pts(args)
            assert(len(cycl_args) > 3)
            O = self.circumcenter(*cycl_args[:3])
            diffs = [self.eqangle6_diff(A, B, D, A, C, D) for A, B, C, D in itertools.combinations(cycl_args, 4)]
            # self.unnamed_circles.append((O, self.dist(O, cycl_args[0])))
            return diffs
        elif pred == "distLt":
            X, Y, A, B = self.lookup_pts(args)
            return [self.max(self.const(0.0), self.dist(X, Y) - dist(A, B))]
        elif pred == "distGt":
            X, Y, A, B = self.lookup_pts(args)
            return [self.max(self.const(0.0), self.dist(A, B) - self.dist(X, Y))]
        elif pred == "eq":
            n1, n2 = [self.eval_num(n) for n in args]
            return [100 * (n1 - n2)]
        elif pred == "gte":
            n1, n2 = [self.eval_num(n) for n in args]
            return [self.max(self.const(0.0), n2 - n1)]
        elif pred == "gt":
            # n1 > n2
            n1, n2 = [self.eval_num(n) for n in args]
            return [self.max(self.const(0.0), (n2 + 1e-1) - n1)]
        elif pred == "lte":
            n1, n2 = [self.eval_num(n) for n in args]
            return [self.max(self.const(0.0), n1 - n2)]
        elif pred == "lt":
            # n1 < n2
            n1, n2 = [self.eval_num(n) for n in args]
            return [self.max(self.const(0.0), (n1 + 1e-1) - n2)]
        elif pred == "eqangle": return [self.eqangle8_diff(*self.lookup_pts(args))]
        elif pred == "eqoangle":
            A, B, C, P, Q, R = self.lookup_pts(args)
            return [self.angle(A, B, C) - self.angle(P, Q, R)]
        elif pred == "eqratio": return [self.eqratio_diff(*self.lookup_pts(args))]
        elif pred == "foot":
            F, X, A, B = self.lookup_pts(args)
            return [self.coll_phi(F, A, B), self.perp_phi(F, X, A, B)]
        elif pred == "ibisector":
            X, B, A, C = self.lookup_pts(args)
            self.segments.extend([(B, A), (A, X), (A, C)])
            return [self.eqangle8_diff(B, A, A, X, X, A, A, C)]
        elif pred == "incenter":
            I, A, B, C = self.lookup_pts(args)
            return [self.dist(I, self.incenter(A, B, C))]
        elif pred == "inPoly": return self.in_poly_phis(*self.lookup_pts(args))
        elif pred == "interLL":
            X, A, B, C, D = self.lookup_pts(args)
            return [self.coll_phi(X, A, B), self.coll_phi(X, C, D)]
        elif pred == "isogonal":
            X, Y, A, B, C = self.lookup_pts(args)
            return [self.dist(X, self.isogonal(Y, A, B, C))]
        elif pred == "midp":
            M, A, B = self.lookup_pts(args)
            return [self.dist(M, self.midp(A, B))]
        elif pred == "onCirc":
            X, C = args
            [X] = self.lookup_pts([X])
            (O, r) = self.circ2nf(C)
            return [self.dist(O, X) - r]
        elif pred == "onLine":
            [X, l] = args
            [X] = self.lookup_pts([X])
            lp1, lp2 = self.line2twoPts(l)
            return [self.coll_phi(X, lp1, lp2)]
        elif pred == "onRay": return [self.coll_phi(*self.lookup_pts(args))] + self.onray_gap(*self.lookup_pts(args))
        elif pred == "onSeg": return [self.coll_phi(*self.lookup_pts(args))] + self.between_gap(*self.lookup_pts(args))
        elif pred == "oppSides":
            A, B, X, Y = self.lookup_pts(args)
            return [self.max(self.const(0.0), self.side_score_prod(A, B, X, Y))]
        elif pred == "orthocenter":
            H, A, B, C = self.lookup_pts(args)
            return [self.dist(H, self.orthocenter(A, B, C))]
        elif pred == "perp":
            if len(args) == 4: # four points
                return [self.perp_phi(*self.lookup_pts(args))]
            else: # two lines
                l1, l2 = args
                P1, P2 = self.line2twoPts(l1)
                P3, P4 = self.line2twoPts(l2)
                return [self.perp_phi(P1, P2, P3, P4)]
        elif pred == "para":
            if len(args) == 4: # four points
                return [self.para_phi(*self.lookup_pts(args))]
            else: # two lines
                l1, l2 = args
                P1, P2 = self.line2twoPts(l1)
                P3, P4 = self.line2twoPts(l2)
                return [self.para_phi(P1, P2, P3, P4)]
        elif pred == "reflectPL":
            X, Y, A, B = self.lookup_pts(args)
            return [self.perp_phi(X, Y, A, B), self.cong_diff(A, X, A, Y)]
        elif pred == "right":
            A, B, C = self.lookup_pts(args)
            return [self.right_phi(A, B, C)]
        # elif pred == "rightTri":
            # A, B, C = self.lookup_pts(args)
            # return [tf.reduce_min([self.right_phi(B, A, C),
                                   # self.right_phi(A, B, C),
                                   # self.right_phi(B, C, A)])]
        elif pred == "sameSide":
            A, B, X, Y = self.lookup_pts(args)
            return [self.max(self.const(0.0), -self.side_score_prod(A, B, X, Y))]
        elif pred == "simtri":
            [A, B, C, P, Q, R] = self.lookup_pts(args)
            self.segments.extend([(A, B), (B, C), (C, A), (P, Q), (Q, R), (R, P)])
            # this is *too* easy to optimize, eqangle properties don't end up holding
            # return [eqratio_diff(A, B, B, C, P, Q, Q, R), eqratio_diff(B, C, C, A, Q, R, R, P), eqratio_diff(C, A, A, B, R, P, P, Q)]
            return [self.eqangle6_diff(A, B, C, P, Q, R), self.eqangle6_diff(B, C, A, Q, R, P), self.eqangle6_diff(C, A, B, R, P, Q)]
        elif pred == "tangentCC":
            # https://mathworld.wolfram.com/TangentCircles.html
            # Could distinguish b/w internally and externally if desired
            c1, c2 = args
            cnf1 ,cnf2 = self.circ2nf(c1), self.circ2nf(c2)
            (x1, y1) = cnf1.center
            (x2, y2) = cnf2.center
            r1, r2 = cnf1.radius, cnf2.radius
            lhs = (x1 - x2) ** 2 + (y1 - y2) ** 2
            rhs_1 = (r1 - r2) ** 2
            rhs_2 = (r1 + r2) ** 2
            return [self.min(lhs - rhs_1, lhs - rhs_2)]
            # inter_point = Point(FuncInfo("interCC", [c1, c2, Root("arbitrary", list())]))
            # return self.assertion_vals("tangentAtCC", [inter_point, c1, c2])
        elif pred == "tangentLC":
            l, c = args
            inter_point = Point(FuncInfo("interLC", [l, c, Root("arbitrary", list())]))
            return self.assertion_vals("tangentAtLC", [inter_point, l, c])
        elif pred == "tangentAtCC":
            p, c1, c2 = args
            c1_center = Point(FuncInfo("origin", [c1]))
            c2_center = Point(FuncInfo("origin", [c2]))

            p_on_c1 = self.assertion_vals("onCirc", [p, c1])
            p_on_c2 = self.assertion_vals("onCirc", [p, c2])
            tangency = self.assertion_vals("coll", [p, c1_center, c2_center])
            return p_on_c1 + p_on_c2 + tangency
        elif pred == "tangentAtLC":
            p, l, c = args
            circ_center = Point(FuncInfo("origin", [c]))
            circ_center_to_p = Line(FuncInfo("connecting", [circ_center, p]))

            p_on_line = self.assertion_vals("onLine", [p, l])
            p_on_circ = self.assertion_vals("onCirc", [p, c])
            tangency = self.assertion_vals("perp", [l, circ_center_to_p])
            return p_on_line + p_on_circ + tangency
        else: raise NotImplementedError(f"[assertion_vals] NYI: {pred}")


    #####################
    ## Comp. Geo
    ####################

    def midp(self, A, B):
        return (A + B).smul(0.5)

    def midp_from(self, M, A):
        return A + (M - A).smul(2)

    def sqdist(self, A, B):
        return (A.x - B.x)**2 + (A.y - B.y)**2

    def dist(self, A, B):
        return self.sqdist(A, B) ** (1 / 2)

    def inner_product(self, A, B):
        a1, a2 = A
        b1, b2 = B
        return a1*b1 + a2*b2

    def scalar_product(self, A, O, B):
        lhs = (A.x - O.x) * (B.x - O.x)
        rhs = (A.y - O.y) * (B.y - O.y)
        return lhs + rhs

    def matrix_mul(self, mat, pt):
        pt1, pt2 = mat
        return self.get_point(self.inner_product(pt1, pt), self.inner_product(pt2, pt))

    def rotation_matrix(self, theta):
        r1 = self.get_point(self.cos(theta), -self.sin(theta))
        r2 = self.get_point(self.sin(theta), self.cos(theta))
        return (r1, r2)

    def rotate_counterclockwise(self, theta, pt):
        return self.matrix_mul(self.rotation_matrix(theta), pt)

    def rotate_clockwise_90(self, pt):
        return self.matrix_mul(
            (self.get_point(self.const(0.0), self.const(1.0)),
             self.get_point(self.const(-1.0),self.const(0.0))),
            pt)

    def rotate_counterclockwise_90(self, pt):
        return self.matrix_mul(
            (self.get_point(self.const(0.0), self.const(-1.0)),
             self.get_point(self.const(1.0),self.const(0.0))),
            pt)

    def side_lengths(self, A, B, C):
        return self.dist(B, C), self.dist(C, A), self.dist(A, B)

    def angle(self, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        return self.acos((a**2 + c**2 - b**2) / (2 * a * c))

    def right_phi(self, A, B, C):
        return self.angle(A, B, C) - math.pi / 2

    def conway_vals(self, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        return (b**2 + c**2 - a**2)/2, (c**2 + a**2 - b**2)/2, (a**2 + b**2 - c**2)/2

    def trilinear(self, A, B, C, x, y, z):
        a, b, c = self.side_lengths(A, B, C)
        denom = a * x + b * y + c * z
        return self.get_point((a * x * A.x + b * y * B.x + c * z * C.x) / denom,
                              (a * x * A.y + b * y * B.y + c * z * C.y) / denom)

    def barycentric(self, A, B, C, x, y, z):
        a, b, c = self.side_lengths(A, B, C)
        return self.trilinear(A, B, C, x/a, y/b, z/c)

    def circumcenter(self, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        Sa, Sb, Sc = self.conway_vals(A, B, C)
        res = self.barycentric(A, B, C, a**2 * Sa, b**2 * Sb, c**2 * Sc)
        return res

    def orthocenter(self, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        Sa, Sb, Sc = self.conway_vals(A, B, C)
        return self.barycentric(A, B, C, Sb * Sc, Sc * Sa, Sa * Sb)

    def centroid(self, A, B, C):
        return self.barycentric(A, B, C, 1, 1, 1)

    def incenter(self, A, B, C):
        return self.trilinear(A, B, C, 1, 1, 1)

    def excenter(self, A, B, C):
        return self.trilinear(A, B, C, -1, 1, 1)

    def perp_phi(self, A, B, C, D):
        return (A.x - B.x) * (C.x - D.x) + (A.y - B.y) * (C.y - D.y)

    def para_phi(self, A, B, C, D):
        return (A.x - B.x) * (C.y - D.y) - (A.y - B.y) * (C.x - D.x)

    def cong_diff(self, A, B, C, D):
        return self.sqdist(A, B) - self.sqdist(C, D)

    def coll_phi(self, A, B, C):
        return A.x * (B.y - C.y) + B.x * (C.y - A.y) + C.x * (A.y - B.y)

    def between_gap(self, X, A, B):
        eps = 0.2

        A1 = self.get_point(A.x + eps * (B.x - A.x), A.y + eps * (B.y - A.y))
        B1 = self.get_point(B.x + eps * (A.x - B.x), B.y + eps * (A.y - B.y))

        return [self.diff_signs(X.x - A1.x, X.x - B1.x), self.diff_signs(X.y - A1.y, X.y - B1.y)]

    def onray_gap(self, X, A, B):
        eps = 0.2
        A1 = self.get_point(A.x + eps * (B.x - A.x), A.y + eps * (B.y - A.y))

        # TODO: coll_phi causing NaNs when [X, A, B] are perfectly collinear by construction
        return [self.diff_signs(X.x - A1.x, A1.x - B.x), self.diff_signs(X.y - A1.y, A1.y - B.y)]

    def det3(self, A, O, B):
        lhs = (A.x - O.x) * (B.y - O.y)
        rhs = (A.y - O.y) * (B.x - O.x)
        return lhs - rhs

    def side_score_prod(self, a, b, x, y):
        return self.det3(a, x, y) * self.det3(b, x, y)

    def opp_sides(self, a, b, x, y):
        return self.lt(self.side_score_prod(a, b, x, y), 0.0)

    def same_side(self, a, b, x, y):
        return self.gt(self.side_score_prod(a, b, x, y), 0.0)

    def inter_ll(self, l1, l2):
        (n11, n12), r1 = l1 # TODO(jesse): ensure that this pattern matching works
        (n21, n22), r2 = l2

        def inter_ll_aux(n11, n12, r1, n21, n22, r2):
            numer = n11 * r2 * (n21 ** 2 + n22**2) - r1 * (n11**2 * n21 + n12**2 * n21)
            denom = n11 * n22 - n12 * n21
            def on_ok():
                return numer/denom

            def on_bad():
                return numer/(tf.math.sign(denom) * 1e-4)

            return tf.cond(tf.less(tf.math.abs(denom), 1e-4),
                           on_bad,
                           on_ok)

        return self.get_point(x=inter_ll_aux(n22, n21, r2, n12, n11, r1),
                              y=inter_ll_aux(n11, n12, r1, n21, n22, r2))

    def inter_pp_c(self, P1, P2, cnf):
        # We follow http://mathworld.wolfram.com/Circle-LineIntersection.html
        O, r = cnf
        P1, P2 = self.shift(O, [P1, P2])

        dx = P1.x - P2.x
        dy = P1.y - P2.y

        dr = self.sqrt(dx**2 + dy**2)
        D = P2.x * P1.y - P1.x * P2.y

        radicand = r**2 * dr**2 - D**2

        def on_nneg():
            def sgnstar(x):
                return self.cond(self.lt(x, self.const(0.0)), lambda: self.const(-1.0), lambda: self.const(1.0))

            # NEXT: Change to self....
            Q1 = self.get_point((D * dy + sgnstar(dy) * dx * self.sqrt(radicand)) / (dr**2),
                                (-D * dx + self.abs(dy) * self.sqrt(radicand)) / (dr**2))

            Q2 = self.get_point((D * dy - sgnstar(dy) * dx * self.sqrt(radicand)) / (dr**2),
                                (-D * dx - self.abs(dy) * self.sqrt(radicand)) / (dr**2))
            return self.unshift(O, [Q1, Q2])

        def on_neg():
            Operp = self.rotate_counterclockwise_90(P1 - P2) + O
            F = self.inter_ll(self.pp2lnf(P1, P2), self.pp2lnf(O, Operp))
            X = O + (F - O).smul(r / self.dist(O, F))
            Q = self.midp(F, X)
            return self.unshift(O, [Q, Q])

        return self.cond(self.lt(radicand, self.const(0.0)), on_neg, on_nneg)

    def inter_lc(self, lnf, c, root_select):
        p1, p2 = self.lnf2pp(lnf)
        I1, I2 = self.inter_pp_c(p1, p2, c)
        return self.process_rs(I1, I2, root_select)

    def inter_cc(self, cnf1, cnf2, root_select):
        l = self.radical_axis(cnf1, cnf2)
        result = self.inter_lc(l, cnf1, root_select)
        return result

    def make_lc_intersect(self, name, lnf, c):
        A, B = self.lnf2pp(lnf)
        O, r = c
        Operp = self.rotate_counterclockwise_90(A - B) + O

        F = self.inter_ll(lnf, self.pp2lnf(O, Operp))
        d = self.dist(O, F)
        f_val = self.cond(self.lt(r, d), lambda: d, lambda: self.const(0.0))

        loss = self.cond(self.logical_or(self.lt(self.dist(O, Operp), 1e-6),
                                         self.lt(self.dist(A, B), 1e-6)),
                         lambda: self.const(0.0), lambda: f_val)
        self.register_loss(f"interLC_{name}", loss, weight=1e-1)

    def second_meet_pp_c(self, A, B, O):
        P1, P2 = self.inter_pp_c(A, B, CircleNF(O, self.dist(O, A)))
        return self.cond(self.lt(self.sqdist(A, P1), self.sqdist(A, P2)), lambda: P2, lambda: P1)

    def amidp_opp(self, B, C, A):
        O = self.circumcenter(A, B, C)
        I = self.incenter(A, B, C)
        return self.second_meet_pp_c(A, I, O)

    def amidp_same(self, B, C, A):
        M = self.amidp_opp(B, C, A)
        O = self.circumcenter(A, B, C)
        return self.second_meet_pp_c(M, O, O)


    def radical_axis_pts(self, cnf1, cnf2):
        (c1x, c1y), r1 = cnf1
        (c2x, c2y), r2 = cnf2

        A = self.const(2.0) * (c2x - c1x)
        B = self.const(2.0) * (c2y - c1y)
        C = (r1**2 - r2**2) + (c2y**2 - c1y**2) + (c2x**2 - c1x**2)

        # FIXME: Fails on EGMO 2.7 because we aren't passing around lambdas anymore
        # pdb.set_trace()
        test = self.gt(self.abs(A), 1e-6)
        p1 = self.cond(test,
                       lambda: self.get_point(x=(C-B)/A, y=self.const(1.0)),
                       lambda: self.get_point(x=self.const(1.0), y=C/B))
        p2 = self.cond(test,
                       lambda: self.get_point(x=C/A, y=self.const(0.0)),
                       lambda: self.get_point(x=self.const(0.0), y=C/B))

        return p1, p2

    def radical_axis(self, cnf1, cnf2):
        p1, p2 = self.radical_axis_pts(cnf1, cnf2)
        return self.pp2lnf(p1, p2)

    def eqangle6_diff(self, A, B, C, P, Q, R):
        s1 = self.det3(A, B, C)
        c1 = self.scalar_product(A, B, C)
        s2 = self.det3(P, Q, R)
        c2 = self.scalar_product(P, Q, R)
        return 0.1 * (s1 * c2 - s2 * c1)

    def eqratio_diff(self, A, B, C, D, P, Q, R, S):
        # AB/CD = PQ/RS
        return self.sqrt(self.dist(A, B) * self.dist(R, S)) - self.sqrt(self.dist(P, Q) * self.dist(C, D))

    def cycl_diff(self, A, B, C, D):
        return self.eqangle6_diff(A, B, D, A, C, D)

    def eqangle8_diff(self, A, B1, B2, C, P, Q1, Q2, R):
        return self.eqangle6_diff(A, B1, C - B2 + B1, P, Q1, R - Q2 + Q1)

    def semiperimeter(self, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        return (a + b + c) / 2

    def area(self, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        s = self.semiperimeter(A, B, C)
        return self.sqrt(s * (s - a) * (s - b) * (s - c))

    def inradius(self, A, B, C):
        return self.area(A, B, C) / self.semiperimeter(A, B, C)

    def exradius(self, A, B, C):
        r = self.inradius(A, B, C)
        a, b, c = self.side_lengths(A, B, C)
        s = (a + b + c)/2
        return r * s / (s - a)

    def mixtilinear_incenter(self, A, B, C):
        ta, tb, tc = self.angle(C, A, B), self.angle(A, B, C), self.angle(B, C, A)
        return self.trilinear(A, B, C, (1/2) * (1 + self.cos(ta) - self.cos(tb) - self.cos(tc)), 1, 1)

    def mixtilinear_inradius(self, A, B, C):
        r = self.inradius(A, B, C)
        ta = self.angle(C, A, B)
        return r * (1 / self.cos(ta / 2)**2)


    def to_trilinear(self, P, A, B, C):
        la = self.pp2lnf(B, C)
        lb = self.pp2lnf(C, A)
        lc = self.pp2lnf(A, B)

        ga = self.pp2lnf(P, P + self.rotate_counterclockwise_90(C - B))
        gb = self.pp2lnf(P, P + self.rotate_counterclockwise_90(A - C))
        gc = self.pp2lnf(P, P + self.rotate_counterclockwise_90(B - A))

        da = self.dist(P, self.inter_ll(la, ga))
        db = self.dist(P, self.inter_ll(lb, gb))
        dc = self.dist(P, self.inter_ll(lc, gc))

        da = self.cond(self.opp_sides(P, A, B, C), lambda: -da, lambda: da)
        db = self.cond(self.opp_sides(P, B, C, A), lambda: -db, lambda: db)
        dc = self.cond(self.opp_sides(P, C, A, B), lambda: -dc, lambda: dc)
        return da, db, dc

    def invert_or_zero(self, x):
        return self.cond(self.abs(x) < 1e-5, lambda: self.const(0.0), lambda: self.const(1) / x)

    def isogonal(self, P, A, B, C):
        x, y, z = self.to_trilinear(P, A, B, C)
        return self.trilinear(A, B, C, self.invert_or_zero(x), self.invert_or_zero(y), self.invert_or_zero(z))

    def isotomic(self, P, A, B, C):
        a, b, c = self.side_lengths(A, B, C)
        x, y, z = self.to_trilinear(P, A, B, C)
        return self.trilinear(A, B, C, (a**2) * self.invert_or_zero(x), (b**2) * self.invert_or_zero(y), (c**2) * self.invert_or_zero(z))


    def inverse(self, X, O, A):
        return O + (X - O).smul(self.sqdist(O, A) / self.sqdist(O, X))

    def harmonic_l_conj(self, X, A, B):
        # see picture in https://en.wikipedia.org/wiki/Projective_harmonic_conjugate
        # L is arbitrary here, not on the line X A B
        # (could also do case analysis and cross-ratio)
        L = A + self.rotate_counterclockwise(const(math.pi / 3), X - A).smul(0.5)
        M = self.midp(A, L)
        N = self.inter_ll(self.pp2lnf(B, L), self.pp2lnf(X, M))
        K = self.inter_ll(self.pp2lnf(A, N), self.pp2lnf(B, M))
        Y = self.inter_ll(self.pp2lnf(L, K), self.pp2lnf(A, X))
        return Y

    def in_poly_phis(self, X, *Ps):
        phis = []
        n = len(Ps)
        for i in range(n):
            A, B, C = Ps[i], Ps[(i+1) % n], Ps[(i+2) % n]
            # X and C are on the same side of AB
            phis.append(self.max(self.const(0.0), - self.side_score_prod(X, C, A, B)))
        return phis


    #####################
    ## Utilities
    ####################

    def line2twoPts(self, l):
        if isinstance(l.val, str):
            L = self.name2line[l]
            return self.lnf2pp(L)
        elif isinstance(l.val, FuncInfo):
            pred, args = l.val
            if pred == "connecting":
                return self.lookup_pts(args)
            elif pred == "paraAt":
                X, A, B = self.lookup_pts(args)
                return X, X + B - A
            elif pred == "perpAt":
                X, A, B = self.lookup_pts(args)
                return X, X + self.rotate_counterclockwise_90(A - B)
            elif pred == "perpBis":
                a, b = args
                m_ab = Point(FuncInfo("midp", [a, b]))
                return self.line2twoPts(Line(FuncInfo("perpAt", [m_ab, a, b])))
            elif pred == "mediator":
                A, B = self.lookup_pts(args)
                M = self.midp(A, B)
                return M, M + self.rotate_counterclockwise_90(A - B)
            elif pred == "ibisector":
                A, B, C = self.lookup_pts(args)
                X = B + (A - B).smul(self.dist(B, C) / self.dist(B, A))
                M = self.midp(X, C)
                return B, M
            elif pred == "ebisector":
                A, B, C = self.lookup_pts(args)
                X = B + (A - B).smul(self.dist(B, C) / self.dist(B, A))
                M = self.midp(X, C)
                Y = B + self.rotate_counterclockwise_90(M - B)
                return B, Y
            elif pred == "eqoangle":
                B, C, D, E, F = self.lookup_pts(args)
                theta = self.angle(D, E, F)
                X = B + self.rotate_counterclockwise(theta, C - B)
                self.segments.extend([(A, B), (B, C), (P, Q), (Q, R)])
                return B, X
            elif pred == "reflectLL":
                l1, l2 = args
                lnf1 = self.line2nf(l1)
                p1, p2 = self.lnf2pp(lnf1)
                refl_p1 = Point(FuncInfo("reflectPL", [Point(FuncInfo("__val__", [p1])), l2]))
                refl_p1 = self.lookup_pt(refl_p1)
                refl_p2 = Point(FuncInfo("reflectPL", [Point(FuncInfo("__val__", [p2])), l2]))
                refl_p2 = self.lookup_pt(refl_p2)
                return refl_p1, refl_p2
            else:
                raise RuntimeError(f"[line2twoPts] Unexpected line pred: {pred}")
        else:
            raise RuntimeError(f"Unsupported line type: {type(l)}")

    def line2sf(self, l):
        if isinstance(l.val, str):
            return self.name2line[l]
        else:
            p1, p2 = self.line2twoPts(l)
            return self.pp2sf(p1, p2)

    def lnf2pp(self, lnf):
        n, r = lnf
        w = n.smul(r)
        m = self.rotate_clockwise_90(n)
        return w, w + m

    def pp2lnf(self, p1, p2):

        # TODO(jesse): please name this
        def mysterious_pp2pp(p1, p2):
            x,y = p2
            def pred(x,y):
                return tf.logical_or(tf.math.less(y, self.const(0.0)),
                                     tf.logical_and(tf.equal(y, self.const(0.0)), tf.math.less(x, self.const(0.0))))
            return tf.compat.v1.cond(pred(x,y), lambda:(p1, p2.smul(-1.0)), lambda:(p1, p2))

        def pp2lnf_core(p1, p2):
            p1, p2 = mysterious_pp2pp(p1, p2)
            x , _ = p2
            n = tf.compat.v1.cond(tf.less_equal(x,0.0), lambda: self.rotate_clockwise_90(p2), lambda: self.rotate_counterclockwise_90(p2))
            r = self.inner_product(p1, n)
            return LineNF(n=n, r=r)

        return pp2lnf_core(p1, (p1 - p2).normalize())


    def line2nf(self, l):
        if isinstance(l.val, str):
            return self.name2line[l]
        else:
            p1, p2 = self.line2twoPts(l)
            return self.pp2lnf(p1, p2)

    def pp2sf(self, p1, p2):
        def vert_line():
            return LineSF(self.const(1.0), self.const(0.0), p1.x, p1, p2)

        def horiz_line():
            return LineSF(self.const(0.0), self.const(1.0), p1.y, p1, p2)

        def calc_sf_from_slope_intercept():
            (x1, y1) = p1
            (x2, y2) = p2

            m = (y2 - y1) / (x2 - x1)
            b = y1 - m * x1
            # y = mx + b ---> -mx + (1)y = b
            return LineSF(-m, self.const(1.0), b, p1, p2)

        return self.cond(self.eq(p1.x, p2.x),
                         vert_line,
                         lambda: self.cond(self.eq(p1.y, p2.y),
                                           horiz_line,
                                           calc_sf_from_slope_intercept))

    def circ2nf(self, circ):

        if isinstance(circ.val, str):
            return self.name2circ[circ]
        elif isinstance(circ.val, FuncInfo):

            pred, args = circ.val

            if pred == "c3" or pred == "circumcircle":
                A, B, C = self.lookup_pts(args)
                O = self.circumcenter(A, B, C)
                return CircleNF(center=O, radius=self.dist(O, A))
            elif pred == "coa":
                O, A = self.lookup_pts(args)
                return CircleNF(center=O, radius=self.dist(O, A))
            elif pred == "cong":
                O, X, Y = self.lookup_pts(args)
                return CircleNF(center=O, radius=self.dist(X, Y))
            elif pred == "diam":
                B, C = self.lookup_pts(args)
                O = self.midp(B, C)
                return CircleNF(center=O, radius=self.dist(O, B))
            elif pred == "incircle":
                A, B, C = self.lookup_pts(args)
                I = self.incenter(A, B, C)
                return CircleNF(center=I, radius=self.inradius(A, B, C))
            elif pred == "excircle":
                A, B, C = self.lookup_pts(args)
                I = self.excenter(A, B, C)
                return CircleNF(center=I, radius=self.exradius(A, B, C))
            elif pred == "mixtilinearIncircle":
                A, B, C = self.lookup_pts(args)
                I = self.mixtilinear_incenter(A, B, C)
                return CircleNF(center=I, radius=self.mixtilinear_inradius(A, B, C))
            else:
                raise RuntimeError(f"[circ2nf] NYI: {pred}")
        else:
            raise RuntimeError("Invalid circle type")

    def shift(self, O, Ps):
        return [self.get_point(P.x - O.x, P.y - O.y) for P in Ps]

    def unshift(self, O, Ps):
        return [self.get_point(P.x + O.x, P.y + O.y) for P in Ps]

    def pt_eq(self, p1, p2):
        return self.lt(self.dist(p1, p2), 1e-6)

    def pt_neq(self, p1, p2):
        return self.gt(self.dist(p1, p2), 1e-6)

    def process_rs(self, P1, P2, root_select):
        pred = root_select.pred
        rs_args = root_select.vars
        if pred == "neq":
            [pt] = self.lookup_pts(rs_args)
            return self.cond(self.pt_neq(P1, pt), lambda: P1, lambda: P2)
        elif pred == "closerTo":
            [pt] = self.lookup_pts(rs_args)
            test = self.lte(self.sqdist(P1, pt), self.sqdist(P2, pt))
            return self.cond(test, lambda: P1, lambda: P2)
        elif pred == "furtherFrom":
            [pt] = self.lookup_pts(rs_args)
            test = self.lt(self.sqdist(P2, pt), self.sqdist(P1, pt))
            return self.cond(test, lambda: P1, lambda: P2)
        elif pred == "oppSides":
            [pt] = self.lookup_pts([rs_args[0]])
            a, b = self.lnf2pp(self.line2nf(rs_args[1]))
            return self.cond(self.opp_sides(P1, pt, a, b), lambda: P1, lambda: P2)
        elif pred == "sameSide":
            [pt] = self.lookup_pts([rs_args[0]])
            a, b = self.lnf2pp(self.line2nf(rs_args[1]))
            return self.cond(self.same_side(P1, pt, a, b), lambda: P1, lambda: P2)
        elif pred == "arbitrary":
            return P2
        else:
            raise NotImplementedError(f"[process_rs] NYI: {pred}")

    def points_far_enough_away(self, name2pt, min_dist):
        for a, b in itertools.combinations(name2pt.keys(), 2):
            A, B = name2pt[a], name2pt[b]
            d = self.dist(A, B)
            if d < min_dist:
                if self.verbosity > 0:
                    print(f"DUP: {a} {b}")
                return False
        return True

    def diff_signs(self, x, y):
        return self.max(self.const(0.0), x * y)
