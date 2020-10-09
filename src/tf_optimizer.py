import tensorflow.compat.v1 as tf
import pdb
import collections
import random
import itertools

from optimizer import Optimizer, LineSF, CircleNF
from diagram import Diagram

class TfPoint(collections.namedtuple("TfPoint", ["x", "y"])):
    def __add__(self, p):  return TfPoint(self.x + p.x, self.y + p.y)
    def __sub__(self, p):  return TfPoint(self.x - p.x, self.y - p.y)
    def sdiv(self, z):     return TfPoint(self.x / z, self.y / z)
    def smul(self, z):     return TfPoint(self.x * z, self.y * z)
    def to_tf(self):       return tf.cast([self.x, self.y], dtype=tf.float64)
    def norm(self):        return tf.norm(self.to_tf(), ord=2)
    def normalize(self):   return self.sdiv(self.norm())
    def has_nan(self):     return tf.logical_or(tf.math.is_nan(self.x), tf.math.is_nan(self.y))
    def __str__(self):     return "(coords %f %f)" % (self.x, self.y)

class TfOptimizer(Optimizer):

    def __init__(self, instructions, opts, graph):
        tfcfg = tf.ConfigProto(intra_op_parallelism_threads=1, inter_op_parallelism_threads=1)
        self.sess = tf.Session(graph=graph, config=tfcfg)

        super().__init__(instructions, opts)

    def get_point(self, x, y):
        return TfPoint(x, y)

    def simplify(self, p, method="all"):
        return p

    def mkvar(self, name, shape=[], lo=-1.0, hi=1.0, trainable=None):
        init = tf.random_uniform_initializer(minval=lo, maxval=hi)
        return tf.compat.v1.get_variable(name=name, shape=shape, dtype=tf.float64, initializer=init, trainable=trainable)

    #####################
    ## Math Utilities
    ####################
    def sum(self, xs):
        return tf.reduce_sum(xs)

    def sqrt(self, x):
        return tf.math.sqrt(x)

    def sin(self, x):
        return tf.math.sin(x)

    def cos(self, x):
        return tf.math.cos(x)

    def asin(self, x):
        return tf.math.asin(x)

    def acos(self, x):
        return tf.math.acos(x)

    def tanh(self, x):
        return tf.nn.tanh(x)

    def sigmoid(self, x):
        return tf.nn.sigmoid(x)

    def const(self, x):
        return tf.constant(x, dtype=tf.float64)

    def max(self, x, y):
        return tf.maximum(x, y)

    def cond(self, cond, t_lam, f_lam):
        return tf.cond(cond, t_lam, f_lam)

    def lt(self, x, y):
        return tf.less(x, y)

    def lte(self, x, y):
        return tf.less_equal(x, y)

    def gt(self, x, y):
        return tf.greater(x, y)

    def gte(self, x, y):
        return tf.greater_equal(x, y)

    def eq(self, x, y):
        return tf.math.equal(x, y)

    def logical_or(self, x, y):
        return tf.logical_or(x, y)

    def abs(self, x):
        return tf.math.abs(x)

    def exp(self, x):
        return tf.math.exp(x)

    #####################
    ## Tensorflow Utilities
    ####################

    def mk_non_zero(self, err):
        res = tf.reduce_mean(tf.exp(- (err ** 2) * 20))
        tf.check_numerics(res, message="mk_non_zero")
        return res

    def mk_zero(self, err):
        res = tf.reduce_mean(err**2)
        tf.check_numerics(res, message="mk_zero")
        return res

    def register_pt(self, p, P):
        assert(p not in self.name2pt)
        assert(isinstance(p.val, str))
        Px = tf.debugging.check_numerics(P.x, message=str(p))
        Py = tf.debugging.check_numerics(P.y, message=str(p))
        self.name2pt[p] = self.get_point(Px, Py)

    def register_line(self, l, L):
        assert(l not in self.name2line)
        assert(isinstance(l.val, str))
        a = tf.debugging.check_numerics(L.a, message=str(l))
        b = tf.debugging.check_numerics(L.b, message=str(l))
        c = tf.debugging.check_numerics(L.c, message=str(l))
        self.name2line[l] = LineSF(a, b, c, L.p1, L.p2)

    def register_circ(self, c, C):
        assert(c not in self.name2circ)
        assert(isinstance(c.val, str))
        r = tf.debugging.check_numerics(C.radius, message=str(c))
        self.name2circ[c] = CircleNF(center=C.center, radius=r)


    def register_loss(self, key, val, weight=1.0):
        assert(key not in self.losses)
        # TF has a bug that causes nans when differentiating something exactly 0
        self.losses[key] = weight * self.mk_zero(val + 1e-6 * (random.random() / 2))

    def register_ndg(self, key, val, weight=1.0):
        assert(key not in self.ndgs)
        err = weight * self.mk_non_zero(val)
        self.ndgs[key] = err
        if self.opts['ndg_loss'] > 0:
            self.register_loss(key, err, self.opts['ndg_loss'])

    def register_goal(self, key, val):
        assert(key not in self.goals)
        self.goals[key] = self.mk_zero(val)

    def regularize_points(self):
        norms = tf.cast([p.norm() for p in self.name2pt.values()], dtype=tf.float64)
        self.register_loss("points", tf.reduce_mean(norms), self.opts['regularize_points'])
        # self.losses["points"] = self.opts.regularize_points * tf.reduce_mean(norms)

    def make_points_distinct(self):
        if random.random() < self.opts['distinct_prob']:
            distincts = tf.cast([self.dist(A, B) for A, B in itertools.combinations(self.name2pt.values(), 2)], tf.float64)
            dloss     = tf.reduce_mean(self.mk_non_zero(distincts))
            self.register_loss("distinct", dloss, self.opts['make_distinct'])
            # self.losses["distinct"] = self.opts.make_distinct * dloss

    def freeze(self):
        opts = self.opts
        self.regularize_points()
        self.make_points_distinct()
        self.loss = sum(self.losses.values())
        self.global_step = tf.train.get_or_create_global_step()
        self.learning_rate = tf.train.exponential_decay(
            global_step=self.global_step,
            learning_rate=opts['learning_rate'],
            decay_steps=opts['decay_steps'],
            decay_rate=opts['decay_rate'],
            staircase=False)
        optimizer         = tf.train.AdamOptimizer(learning_rate=self.learning_rate)
        gs, vs            = zip(*optimizer.compute_gradients(self.loss))
        self.apply_grads  = optimizer.apply_gradients(zip(gs, vs), name='apply_gradients', global_step=self.global_step)
        self.reset_step   = tf.assign(self.global_step, 0)

    def print_losses(self):
        print("======== Print losses ==========")
        print("-- Losses --")
        for k, x in self.run(self.losses).items(): print("  %-50s %.10f" % (k, x))
        print("-- Goals --")
        for k, x in self.run(self.goals).items(): print("  %-50s %.10f" % (k, x))
        print("-- NDGs --")
        for k, x in self.run(self.ndgs).items(): print("  %-50s %.10f" % (k, x))
        print("================================")

    def train(self):
        opts = self.opts
        self.sess.run(self.reset_step)
        self.sess.run(tf.compat.v1.global_variables_initializer())

        loss_v = None

        for i in range(opts['n_iterations']):
            loss_v, learning_rate_v = self.sess.run([self.loss, self.learning_rate])
            '''
            if i > 0 and i % opts.print_freq == 0:
                if opts.verbose: print("[%6d] %16.12f || %10.6f" % (i, loss_v, learning_rate_v))
                if opts.verbose > 1: self.print_losses()
                if opts.plot > 1: self.plot()
            '''
            # print("[%6d] %16.12f || %10.6f" % (i, loss_v, learning_rate_v))
            # self.print_losses()
            # self.get_model().plot()
            if loss_v < opts['eps']:
                '''
                check_points_far_enough_away(self.run(self.name2pt), self.opts.min_dist)
                if opts.verbose: print("DONE: %f" % loss_v)
                if opts.verbose: self.print_losses()
                if opts.plot: self.plot()
                '''
                self.print_losses()
                return loss_v
            else:
                self.sess.run(self.apply_grads)

        return loss_v


    #####################
    ## Core
    ####################

    def get_model(self):
        pt_assn, line_assn, circ_assn, segments, circles, ndgs, goals = self.run([
            self.name2pt, self.name2line, self.name2circ, self.segments, self.circles, self.ndgs, self.goals])
        return Diagram(points=pt_assn, lines=line_assn, segments=segments, circles=circles, ndgs=ndgs, goals=goals, no_plot_pts=self.no_plot_pts, named_circles=circ_assn)

    def run(self, x):
        return self.sess.run(x)

    def solve(self):
        if self.has_loss:
            self.freeze()
            # raise NotImplementedError("[tf_optimizer.solve] Cannot solve with loss")

        models = list()
        for _ in range(self.opts['n_tries']):
            if not self.has_loss:
                self.run(tf.compat.v1.global_variables_initializer())
                pt_assn = self.run(self.name2pt)
                if self.points_far_enough_away(pt_assn, self.opts['min_dist']):
                    self.print_losses()
                    models.append(self.get_model())
            else:
                loss = None
                try:
                    loss = self.train()
                except Exception as e:
                    print(f"ERROR: {e}")

                if loss is not None and loss < self.opts['eps']:
                    pt_assn = self.run(self.name2pt)
                    if self.points_far_enough_away(pt_assn, self.opts['min_dist']):
                        models.append(self.get_model())
        return models
