from typing import Callable

import numpy as np
import torch
import torch.nn.functional as F


# adapted from https://github.com/valerystrizh/pytorch-histogram-loss
class LabelDistributionLoss(torch.nn.Module):
    """Label distribution loss.

    Attributes:
        prior: the prior probability of positive class.
        device: the device to use.
        step: the bin width.
        num_bins: the number of bins.
        proxy: the proxy distribution.
        dist: the distance function.
        t: the tensor of bin centers.
        t_size: the size of t.
    """

    def __init__(self, prior, device, num_bins=1, proxy="polar", dist="L1"):
        super(LabelDistributionLoss, self).__init__()
        self.prior = prior
        self.frac_prior = 1.0 / (2 * prior)

        self.step = 1 / num_bins  # bin width. predicted scores in [0, 1].
        self.device = device
        self.t = (
            torch.arange(0, 1 + self.step, self.step).view(1, -1).requires_grad_(False)
        )  # [0, 1+bin width)
        self.t_size = num_bins + 1

        self.dist: Callable[..., torch.Tensor]
        if dist == "L1":
            self.dist = F.l1_loss
        else:
            raise NotImplementedError("The distance: {} is not defined!".format(dist))

        # proxy
        proxy_p, proxy_n = None, None
        if proxy == "polar":
            proxy_p = np.zeros(
                self.t_size, dtype=float
            )  # Apparently assumes self.t_size = 2
            proxy_n = np.zeros_like(proxy_p)
            proxy_p[-1] = 1
            proxy_n[0] = 1
        else:
            raise NotImplementedError("The proxy: {} is not defined!".format(proxy))

        proxy_mix = (
            prior * proxy_p + (1 - prior) * proxy_n
        )  # Tensor of (1-prior, prior)
        print("#### Label Distribution Loss ####")
        print("ground truth P:")
        print(proxy_p)
        print("ground truth U:")
        print(proxy_mix)

        # to torch tensor
        self.proxy_p = torch.from_numpy(proxy_p).requires_grad_(False).float()
        self.proxy_mix = torch.from_numpy(proxy_mix).requires_grad_(False).float()

        # to device
        self.t = self.t.to(self.device)
        self.proxy_p = self.proxy_p.to(self.device)
        self.proxy_mix = self.proxy_mix.to(self.device)

    def histogram(self, scores):
        scores_rep = scores.repeat(1, self.t_size)

        hist = torch.abs(scores_rep - self.t)  # (score, 1 - score)
        # Note: self.step = 1 / num_bins = 1
        inds = hist > self.step  # (score - 0 > 1, 1 - score > 1) = (false, false)
        hist = self.step - hist  # switch values
        hist[inds] = 0
        return hist.sum(dim=0) / (
            len(scores) * self.step
        )  # (sum(score), sum(1 - score)) / 2

    def forward(self, outputs, labels):
        scores = torch.sigmoid(outputs)
        labels = labels.view(-1, 1)

        scores = scores.view_as(labels)
        s_p = scores[labels == 1].view(-1, 1)
        s_u = scores[labels == 0].view(-1, 1)

        l_p = 0
        l_u = 0
        if s_p.numel() > 0:
            l_p = self.dist(s_p, torch.ones_like(s_p), reduction="mean")
            # hist_p = self.histogram(s_p)
            # l_p = self.dist(hist_p, self.proxy_p, reduction="mean")
        if s_u.numel() > 0:
            l_u = self.dist(s_u, torch.ones_like(s_u) * self.prior, reduction="mean")
            # hist_u = self.histogram(s_u)
            # l_u = self.dist(hist_u, self.proxy_mix, reduction="mean")

        return l_p + self.frac_prior * l_u
