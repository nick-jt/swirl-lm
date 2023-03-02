# Copyright 2022 The swirl_lm Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Copyright 2023 Google LLC
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
"""A library for generic microphysics models."""
import abc
from typing import Optional

from swirl_lm.base import parameters as parameters_lib
from swirl_lm.physics.thermodynamics import water
import tensorflow as tf


class Microphysics(abc.ABC):
  """A library for generic microphysics models."""

  def __init__(self, params: parameters_lib.SwirlLMParameters):
    """Initializes required libraries required by microphysics models."""
    self._params = params

    model_params = self._params.thermodynamics
    assert model_params is not None, 'Thermodynamics model is not defined.'

    model_type = model_params.WhichOneof('thermodynamics_type')
    assert model_type == 'water', (
        'Microphysics requires `water` to be the thermodynamics model.'
        f' {model_type} is provided.'
    )

    self._water_model = water.Water(self._params)

  @abc.abstractmethod
  def evaporation(self, *args, **kwargs) -> water.FlowFieldVal:
    """Computes the evaporation rate."""
    raise NotImplementedError(
        'Base microphysics model does not have a evaporation model. Please use'
        ' a specific microphysics model instead.'
    )

  @abc.abstractmethod
  def autoconversion_and_accretion(self, *args, **kwargs) -> water.FlowFieldVal:
    """Computes the autoconversion and accretion rate."""
    raise NotImplementedError(
        'Base microphysics model does not have autoconversion and accretion '
        'models. Please use a specific microphysics model instead.'
    )

  @abc.abstractmethod
  def terminal_velocity(self, *args, **kwargs) -> water.FlowFieldVal:
    """Computes the terminal velocity of the precipitation."""
    raise NotImplementedError(
        'Base microphysics model does not have precipitation-terminal velocity '
        'model. Please use a specific microphysics model instead.'
    )

  def condensation(
      self,
      rho: water.FlowFieldVal,
      temperature: water.FlowFieldVal,
      q_v: water.FlowFieldVal,
      q_l: water.FlowFieldVal,
      q_c: water.FlowFieldVal,
      zz: Optional[water.FlowFieldVal] = None,
      additional_states: Optional[water.FlowFieldMap] = None,
  ) -> water.FlowFieldVal:
    """Computes the condensation rate.

    Reference:
    Grabowski, W. W., & Smolarkiewicz, P. K. (1990). Monotone finite-difference
    approximations to the advection-condensation problem. Monthly Weather
    Review, 118(10), 2082–2098.

    Args:
      rho: The moist air density, in kg/m^3.
      temperature: The temperature.
      q_v: The cloud vapor fraction (kg/kg).
      q_l: The specific humidity of the cloud liquid phase (kg/kg).
      q_c: The specific humidity of the cloud humidity condensed phase,
        including ice and liquid (kg/kg).
      zz: The vertical coordinates (m).
      additional_states: Helper variables including those needed to compute
        reference states.

    Returns:
      The condensation rate.
    """
    q_t = tf.nest.map_structure(tf.math.add, q_v, q_c)
    q_i = tf.nest.map_structure(tf.math.subtract, q_c, q_l)
    q_vs = self._water_model.saturation_q_vapor(temperature, rho, q_l, q_c)
    t_0 = self._water_model.t_ref(zz, additional_states)
    # Here we assume that the air is dry in the reference state.
    zeros = tf.nest.map_structure(tf.zeros_like, zz)
    theta_0 = self._water_model.temperature_to_potential_temperature(
        'theta', t_0, zeros, zeros, zeros, zz, additional_states
    )
    theta = self._water_model.temperature_to_potential_temperature(
        'theta', temperature, q_t, q_l, q_i, zz, additional_states
    )
    cp = self._water_model.cp_m(q_t, q_l, q_i)

    def condensation_fn(q_v, q_vs, t_0, theta_0, theta, cp):
      """Computes the condensation rate."""
      return (q_v - q_vs) / (
          1.0
          + q_vs
          * (self._water_model.lh_v0 / cp / t_0)
          * (theta_0 / theta)
          * (
              (self._water_model.lh_v0 / self._water_model.r_v / t_0)
              * (theta_0 / theta)
              - 1.0
          )
      ) / self._params.dt

    return tf.nest.map_structure(
        condensation_fn, q_v, q_vs, t_0, theta_0, theta, cp
    )