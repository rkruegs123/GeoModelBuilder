(param (A B C D) polygon)
(assert (right A B C))
(assert (right C D A))
(let H point (foot A (line B D)))
(param S point (on-seg A B))
(param T point (on-seg A D))
(assert (in-poly H S C T))
(assert (= (div pi 2) (sub (uangle C H S) (uangle C S B))))
(assert (= (div pi 2) (sub (uangle T H C) (uangle D T C))))

(eval (tangent-lc (line B D) (circumcircle T S H)))