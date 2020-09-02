import sexpdata

from constraint import Constraint
from util import *
from compile_state import CompileState
from instruction import Assert, AssertNDG, Confirm, Sample

class Problem:
    def __init__(self, filename):
        self.points = list()
        self.constraints = list()
        self.goals = list()
        self.filename = filename

        for l in open(filename).readlines():
            stripped_l = l.strip()
            if stripped_l and l[0] != ';':
                line_info = sexpdata.loads(stripped_l, true=None)
                if not len(line_info):
                    raise RuntimeError("Empty s-expressions encountered")

                cmd = str(line_info[0]._val)
                if cmd == "declare-points":
                    if self.points:
                        raise RuntimeError("Duplicate declaration of points")
                    if not all(isinstance(p, sexpdata.Symbol) for p in line_info[1:]):
                        raise RuntimeError("Unrecognized load type from sexpdata")
                    self.points = [p._val for p in line_info[1:]]
                elif cmd == "declare-point":
                    if len(line_info) != 2:
                        raise RuntimeError("Mal-formed declare-point")
                    if not isinstance(line_info[1], sexpdata.Symbol):
                        raise RuntimeError("Unrecognized load type from sexpdata")
                    self.points.append(line_info[1]._val)
                else:
                    # FIXME: This check won't handle negations
                    # if not all(isinstance(x, sexpdata.Symbol) for x in line_info[1]):
                        # raise RuntimeError("Unrecognized load type from sexpdata")

                    negate = False
                    if line_info[1][0]._val == "not":
                        negate = True
                        pred, args = line_info[1][1][0]._val, [x._val for x in line_info[1][1][1:]]
                    else:
                        pred, args = line_info[1][0]._val, [x._val for x in line_info[1][1:]]
                    if cmd == "assert":
                        self.constraints.append(Constraint(pred=pred, points=args, negate=negate))
                    elif cmd == "prove":
                        self.goals.append(Constraint(pred=pred, points=args, negate=negate))
                    elif cmd == "watch":
                        print("TODO: Add support for watch cmd")
                    else:
                        raise RuntimeError("Unrecognized command")

    def preprocess(self):
        sample_points = [p for c in self.constraints for p in c.points if is_sample_pred(c.pred)]
        cs_with_sampled_points = [c for c in self.constraints if set(c.points).issubset(set(sample_points))]
        self.sample_bucket = Bucket(points=sample_points, assertions=cs_with_sampled_points)

        solve_points = list(set(self.points) - set(sample_points))
        cs_to_solve = [c for c in self.constraints if not set(c.points).issubset(set(sample_points)) and not c.negate]
        self.solve_bucket = Bucket(points=solve_points, assertions=cs_to_solve)

        self.ndgs = [c for c in self.constraints if c.negate]


    def sample_bucket_2_instructions(self):
        # Get sample instructions
        sample_instructions = list()
        # FIXME: Bad naming -- right, samplers is the thing driving the sampling, while sample_cs are like constraints around that sampling
        samplers = [c for c in self.sample_bucket.assertions if is_sample_pred(c.pred)]
        sample_cs = list(set(self.sample_bucket.assertions) - set(samplers))

        if sample_cs and not samplers:
            raise RuntimeException("Mishandled sampling constraints")

        if not samplers:
            return sample_instructions
        elif len(samplers) > 1:
            raise RuntimeException("Unexpected sampling")

        sampler = samplers[0]

        if sampler.pred == "triangle":  # We know len(samplers) == 1
            tri_points = set(sampler.points)

            iso_points = list(set([collections.Counter(c.points).most_common(1)[0] for c in sample_cs if c.pred == "cong"]))
            acute = any(c.pred == "acutes" and set(c.points) == tri_points for c in sample_cs)
            right_points = list(set([collections.Counter(c.points).most_common(1)[0] for c in sample_cs if c.pred == "perp"]))
            tri_points = list(tri_points)

            # FIXME: Handle all triangle cases
            if not sample_cs:
                sample_instructions.append(Sample(tri_points, "triangle"))
            elif len(sample_cs) == 1 and acute:
                sample_instructions.append(Sample(tri_points, "acuteTri"))
            elif len(sample_cs) == 1 and iso_points:
                sample_instructions.append(Sample(tri_points, ("isoTri", iso_point[0])))
            elif len(sample_cs) == 2 and acute and iso_points:
                sample_instructions.append(Sample(tri_points, ("acuteIsoTri", iso_points[0])))
            elif len(sample_cs) == 2 and len(iso_points) == 2:
                sample_instructions.append(Sample(tri_points, "equiTri"))
            elif len(sample_cs) == 1 and lenright_points:
                sample_instructions.append(Sample(tri_points, ("rightTri", right_points[0])))
            else:
                raise RuntimeException("Unhandled triangle sampling")
        elif samplers[0].pred == "polygon":
            poly_points = set(sampler.points)

            if not sample_cs:
                sample_instructions.append(Sample(poly_points, "polygon"))
            else:
                sample_instructions.append(Sample(poly_points, "polygon"))
                sample_instructions += [Assert(c) for c in sample_cs]
        else:
            raise RuntimeError("Mishandled sampling")

        return sample_instructions


    def validate(self):
        all_bucketed_points = self.sample_bucket.points + self.solve_bucket.points

        for c in self.solve_bucket.assertions:
            for p in (c.points):
                if p not in all_bucketed_points:
                    raise RuntimeException("unexpected point " ++ str(p))
        return

    def solve_bucket_2_instructions(self):

        self.validate()

        solve_compiler = CompileState(self.sample_bucket, self.solve_bucket)
        solve_compiler.solve()

        return solve_compiler.solve_instructions

    def gen_instructions(self):
        self.instructions = list()

        # FIXME: Need instruction type?
        self.instructions += [AssertNDG(c) for c in self.ndgs]
        self.instructions += [Confirm(c) for c in self.goals]

        sample_instructions = self.sample_bucket_2_instructions()
        self.instructions += sample_instructions

        # TODO: Solve instructions
        solve_instructions = self.solve_bucket_2_instructions()
        self.instructions += solve_instructions


    def __str__(self):
        return '\nPROBLEM: {f}\n{header}\n\nPoints: {pts}\nConstraints:\n\t{cs}\nGoals:\n\t{gs}\n'.format(
            f=self.filename,
            header='-' * (9 + len(self.filename)),
            pts=' '.join(self.points),
            cs='\n\t'.join([str(c) for c in self.constraints]),
            gs='\n\t'.join([str(g) for g in self.goals])
    )