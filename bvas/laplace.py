"""
Unlike most of the code in this repository, This code requires pyro.
See https://github.com/pyro-ppl/pyro#installing for installation instructions.
"""
import pyro
import pyro.distributions as dist
import torch
from torch import triangular_solve as trisolve

from bvas.util import safe_cholesky


def laplace_inference(Y, Gamma,
                      coef_scale=1.0e-2, seed=0, num_steps=10 ** 4,
                      log_every=500, init_lr=0.01):
    r"""
    Use Maximum A Posteriori (MAP) inference and a diffusion-based likelihood in conjunction
    with a sparsity-inducing Laplace prior on selection coefficients to infer
    selection effects from genomic surveillance data.

    :param torch.Tensor Y: A torch.Tensor of shape (A,) that encodes integrated alelle frequency
        increments for each allele and where A is the number of alleles.
    :param torch.Tensor Gamma: A torch.Tensor of shape (A, A) that encodes information about
        second moments of allele frequencies.
    :param float coef_scale: The regularization scale of the Laplace prior. Defaults to 0.01.
    :param int seed: Random number seed for reproducibility.
    :param int num_steps: The number of optimization steps to do. Defaults to ten thousand.
    :param int log_every: Controls logging frequency. Defaults to 500.
    :param float init_lr: The initial learning rate. Defaults to 0.01.

    :returns dict: Returns a dictionary of containing the inferred selection coefficients beta.
    """
    pyro.clear_param_store()

    A = Gamma.size(-1)

    L = safe_cholesky(Gamma, num_tries=10)
    L_Y = trisolve(Y.unsqueeze(-1), L, upper=False)[0].squeeze(-1)

    def model():
        beta = pyro.sample("beta", dist.Laplace(0.0, coef_scale * torch.ones(A)).to_event(1))
        pyro.factor("obs", -0.5 * (L.t() @ beta - L_Y).pow(2.0).sum())

    def fit_svi():
        pyro.set_rng_seed(seed)

        guide = pyro.infer.autoguide.AutoDelta(model)
        optim = pyro.optim.ClippedAdam({"lr": init_lr, "lrd": 0.01 ** (1 / num_steps), "betas": (0.5, 0.99)})
        svi = pyro.infer.SVI(model, guide, optim, pyro.infer.Trace_ELBO())

        for step in range(num_steps):
            loss = svi.step()
            if log_every and (step % log_every == 0 or step == num_steps - 1):
                print(f"step {step: >4d} loss = {loss:0.6g}")

        return guide

    beta = fit_svi().median()['beta'].data.cpu().numpy()

    return {'beta': beta}
