// prove_gradient_norm.circom
pragma circom 2.0.0;

include "circomlib/circuits/comparators.circom";

template GradientNormBound(n) {
    // private inputs — client never reveals these
    signal input gradient[n];

    // public inputs — server can verify these
    signal input model_hash;
    signal input client_id;
    signal input round_num;
    signal input norm_bound;   // e.g. 1000 (scaled integer)

    // compute squared norm
    signal sq[n];
    signal cumsum[n+1];
    cumsum[0] <== 0;
    for (var i = 0; i < n; i++) {
        sq[i] <== gradient[i] * gradient[i];
        cumsum[i+1] <== cumsum[i] + sq[i];
    }

    // enforce norm^2 <= norm_bound^2
    component lt = LessEqThan(32);
    lt.in[0] <== cumsum[n];
    lt.in[1] <== norm_bound * norm_bound;
    lt.out === 1;
}

component main {public [model_hash, client_id, round_num, norm_bound]} = GradientNormBound(128);