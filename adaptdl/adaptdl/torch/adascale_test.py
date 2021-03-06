# Copyright 2020 Petuum, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import numpy as np
import pytest
import torch

from unittest.mock import Mock

import adaptdl.torch.adascale as adascale


def test_object():
    params = [torch.tensor([[1., -1.], [2., 3.]], requires_grad=True),
              torch.tensor([[2., 3.]], requires_grad=True)]
    sgd = torch.optim.SGD(params, lr=0.1)
    adp = Mock(require_backward_grad_sync=True)
    obj = adascale.AdaScale(adp, sgd, accum_scale=1.0, num_replicas=1)
    assert(obj._accum_scale == 1.0)
    obj._num_replicas = 8
    obj.set_accum_scale(3.0)
    assert(obj.accum_scale == 3.0)
    obj._num_replicas = 4
    obj.set_accum_scale(3.0)
    assert(obj.accum_scale == 3.0)
    assert(np.isclose(obj.gain(2.0), 1.0))
    obj._state['var_avg'] = 3.0
    obj._state['norm_avg'] = 1.0
    assert(np.isclose(obj.gain(3.0), 2.0))


LR = 0.001
STEP_SCHEDULE = [1000]
ATOL = 0.01


def test_optimization_1():
    # See torch.test.test_optim
    # Also see Rosenbrock/banana function
    def rosenbrock(tensor):
        x, y = tensor
        return (1 - x) ** 2 + 100 * (y - x ** 2) ** 2

    params_t = torch.Tensor([1.0, 1.5])

    params = torch.autograd.Variable(params_t, requires_grad=True)
    sgd = torch.optim.SGD([params], lr=LR)
    schedule = torch.optim.lr_scheduler.MultiStepLR(sgd, STEP_SCHEDULE)
    adp = Mock(require_backward_grad_sync=True)
    adascale.AdaScale(adp, sgd, accum_scale=1.0, num_replicas=1,
                      patch_optimizer=True)
    for i in range(100000):
        sgd.zero_grad()
        loss = rosenbrock(params)
        loss.backward()
        sgd.step()
        schedule.step()
        if params.allclose(torch.tensor([1.0, 1.0]), atol=ATOL):
            break
    else:
        pytest.fail(f"Did not converge: {params}")


def test_optimization_2():

    def rosenbrock_noisy(tensor):
        x, y = tensor
        return (np.random.normal(1.0, 0.2) * (1 - x) ** 2 +
                np.random.normal(1.0, 0.2) * 100 * (y - x ** 2) ** 2)

    params_t = torch.Tensor([1.0, 1.5])

    params = torch.autograd.Variable(params_t, requires_grad=True)
    sgd = torch.optim.SGD([params], lr=LR)
    schedule = torch.optim.lr_scheduler.MultiStepLR(sgd, STEP_SCHEDULE)
    adp = Mock(require_backward_grad_sync=True)
    adascale.AdaScale(adp, sgd, accum_scale=1.0, num_replicas=1,
                      patch_optimizer=True)
    for i in range(100000):
        sgd.zero_grad()
        loss = sum([rosenbrock_noisy(params) for i in range(2)]) / 2.0
        loss.backward()
        sgd.step()
        schedule.step()
        if params.allclose(torch.tensor([1.0, 1.0]), atol=ATOL):
            break
    else:
        pytest.fail(f"Did not converge: {params}")


def test_optimization_3():
    def rosenbrock(x, y):
        return (1 - x) ** 2 + 100 * (y - x ** 2) ** 2

    params_t = [
        {"params": [torch.autograd.Variable(torch.Tensor([1.0]),
                                            requires_grad=True)]},
        {"params": [torch.autograd.Variable(torch.Tensor([1.5]),
                                            requires_grad=True)]}]

    sgd = torch.optim.SGD(params_t, lr=LR)
    schedule = torch.optim.lr_scheduler.MultiStepLR(sgd, STEP_SCHEDULE)
    adp = Mock(require_backward_grad_sync=True)
    adascale.AdaScale(adp, sgd, accum_scale=1.0, num_replicas=1,
                      patch_optimizer=True)
    for i in range(100000):
        sgd.zero_grad()
        loss = rosenbrock(params_t[0]['params'][0], params_t[1]['params'][0])
        loss.backward()
        sgd.step()
        schedule.step()
        if params_t[0]['params'][0].allclose(torch.tensor([1.0]), atol=ATOL) \
                and params_t[1]['params'][0].allclose(torch.tensor([1.0]),
                                                      atol=ATOL):
            break
    else:
        pytest.fail(f"Did not converge: {params_t}")


def test_gradient_accumulation_optimization_1():

    def rosenbrock(tensor):
        x, y = tensor
        return (1 - x) ** 2 + 100 * (y - x ** 2) ** 2

    params_t = torch.Tensor([1.0, 1.5])

    params = torch.autograd.Variable(params_t, requires_grad=True)
    sgd = torch.optim.SGD([params], lr=LR)
    schedule = torch.optim.lr_scheduler.MultiStepLR(sgd, STEP_SCHEDULE)
    adp = Mock(require_backward_grad_sync=False)
    adascale.AdaScale(adp, sgd, accum_scale=1.0, num_replicas=1,
                      patch_optimizer=True)
    for i in range(100000):
        adp.require_backward_grad_sync = i % 2 == 1
        sgd.zero_grad()
        loss = rosenbrock(params)
        loss.backward()
        sgd.step()
        if adp.require_backward_grad_sync:
            schedule.step()
        if params.allclose(torch.tensor([1.0, 1.0]), atol=10 * ATOL):
            break
    else:
        pytest.fail(f"Did not converge: {params}")


def test_gradient_accumulation_optimization_2():

    def rosenbrock_noisy(tensor):
        x, y = tensor
        return (np.random.normal(1.0, 0.2) * (1 - x) ** 2 +
                np.random.normal(1.0, 0.2) * 100 * (y - x ** 2) ** 2)

    params_t = torch.Tensor([1.0, 1.5])

    params = torch.autograd.Variable(params_t, requires_grad=True)
    sgd = torch.optim.SGD([params], lr=LR)
    schedule = torch.optim.lr_scheduler.MultiStepLR(sgd, STEP_SCHEDULE)
    adp = Mock(require_backward_grad_sync=False)
    adascale.AdaScale(adp, sgd, accum_scale=1.0, num_replicas=1,
                      patch_optimizer=True)
    for i in range(1000000):
        adp.require_backward_grad_sync = i % 2 == 1
        sgd.zero_grad()
        loss = rosenbrock_noisy(params)
        loss.backward()
        sgd.step()
        if adp.require_backward_grad_sync:
            schedule.step()
        if params.allclose(torch.tensor([1.0, 1.0]), atol=ATOL):
            break
    else:
        pytest.fail(f"Did not converge: {params}")
