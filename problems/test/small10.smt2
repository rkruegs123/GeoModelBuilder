;; (param myLine line)
;; (param Gamma circle (tangent-cl myLine))
(param myLine line)
(param A point)
(define B point (reflect-pl A myLine))
(eval (on-line A myLine))
