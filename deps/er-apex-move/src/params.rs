//! Raw settings from apex-data/fuse_data.json, movement section.
//! Numeric values are data. The equations using them follow Apex Season 3's own movement code
//! (D-020, docs/research/apex-slide-spec.md); fields marked "convar" are engine console variables
//! read from R5Reloaded, not player settings.
use std::{error::Error, fmt};

#[derive(Clone, Copy, Debug)]
pub struct PoseParams {
    pub height: f32,
    pub radius: f32,
    /// Eye height above the feet.
    pub viewheight: f32,
    pub speed: f32,
    pub sprint_speed: f32,
    /// Below `low_speed` the pose accelerates with `low_acceleration` (negative: unused).
    pub low_speed: f32,
    pub low_acceleration: f32,
    pub acceleration: f32,
    /// Negative: 0.6 times this pose's acceleration (spec section 8).
    pub deceleration: f32,
    pub sprint_acceleration: f32,
    pub sprint_deceleration: f32,
}

#[derive(Clone, Debug)]
pub struct MoveParams {
    /// TODO/待定: global gravity before gravityScale, Apex units/s².
    pub base_gravity: Option<f32>,
    /// TODO/待定: global speed multiplier. No implicit 1.15 factor.
    pub speed_multiplier: Option<f32>,
    /// TODO/待定: meters per Apex unit. Only used by conversion helpers.
    pub meters_per_unit: Option<f32>,
    /// TODO/待定: walkable slope angle in radians; not in the provided asset.
    pub max_slope_radians: Option<f32>,
    pub standing: PoseParams,
    pub crouching: PoseParams,
    pub gravity_scale: f32,
    pub step_height: f32,
    pub jump_height: f32,
    pub air_speed: f32,
    pub air_acceleration: f32,
    pub air_friction: f32,
    /// Only the visual sprint fraction uses it in Apex; speed sprints at once (spec section 5).
    pub sprint_start_delay: f32,
    /// The visual sprint fraction (gun-motion spec §4.1; Fuse's player settings
    /// sprintStartDuration, sprintStartFastDuration, sprintEndDuration in
    /// apex-data/export/settings/player/mp/pilot_survival_fuse_medium.json): seconds to rise after
    /// `sprint_start_delay`, to rise from a sprint start, to fall after the sprint ends.
    pub sprint_start_duration: f32,
    pub sprint_start_fast_duration: f32,
    pub sprint_end_duration: f32,
    /// sprintViewOffset: the eye moves this much (raw units) at the full sprint fraction.
    pub sprint_view_offset: f32,
    pub speed_scale_side: f32,
    pub speed_scale_back: f32,
    pub can_jump_while_crouched: bool,
    pub anti_multi_jump_height_frac: f32,
    pub anti_multi_jump_time_min: f32,
    pub anti_multi_jump_time_max: f32,
    pub air_drag: f32,
    pub land_slowdown_duration: f32,
    pub land_slowdown_frac: f32,
    pub land_slowdown_time_power: f32,
    pub land_slowdown_height_min: f32,
    pub land_slowdown_height_max: f32,
    pub land_slowdown_no_sprint_frac: f32,
    pub mantle_height: f32,
    pub climb_height: f32,
    pub slide_enabled: bool,
    pub sprint_enabled: bool,
    pub crouch_enabled: bool,
    pub automantle: bool,
    pub climb_enabled: bool,
    pub slide_required_start_speed: f32,
    /// Landing faster than 200 units/s downwards (spec section 13).
    pub slide_required_start_speed_air: f32,
    pub slide_speed_boost: f32,
    pub slide_speed_boost_cap: f32,
    pub slide_boost_cooldown: f32,
    pub slide_decel: f32,
    /// Crouch released (still sliding above `slide_max_stop_speed`) or pulling back.
    pub slide_want_to_stop_decel: f32,
    /// Speed retained per second after the linear deceleration (times 0.7^dt).
    pub slide_velocity_decay: f32,
    /// Acceleration while sliding: sideways steering only.
    pub slide_accel: f32,
    pub slide_jump_height: f32,
    pub slide_stop_speed: f32,
    /// Above this the slide goes on with crouch released.
    pub slide_max_stop_speed: f32,
    pub slide_max_jump_speed: f32,
    /// convar slide_max_angle_dot: grounded slides need the move input this close to the view.
    pub slide_max_angle_dot: f32,
    /// convar slide_step_velocity_reduction: speed lost per unit of step climbed while sliding.
    pub slide_step_velocity_reduction: f32,
    /// convar slide_whileInAir.
    pub slide_while_in_air: bool,
    /// convar slide_auto_stand: a finished slide also releases toggled crouch.
    pub slide_auto_stand: bool,
    /// convar jump_graceperiod: seconds after leaving the ground a jump is still allowed.
    pub jump_grace_period: f32,
    /// convars skip_*: jumping within `skip_time` of landing loses `skip_speed_reduce`, not below
    /// `skip_speed_retain` (negative: the standing sprint speed).
    pub skip_time: f32,
    pub skip_speed_reduce: f32,
    pub skip_speed_retain: f32,
    pub skip_jump_height_speed: f32,
    pub skip_jump_height_fraction: f32,
    /// convar player_extraairaccelleration.
    pub extra_air_acceleration: f32,
    /// Numerical collision tolerance, not an Apex gameplay parameter.
    pub skin: f32,
    /// Collision iteration budget, not an Apex gameplay parameter.
    pub collision_iterations: usize,
    /// Numerical ledge probing range beyond the capsule radius, raw units.
    pub ledge_probe_distance: f32,
}

impl Default for MoveParams {
    fn default() -> Self {
        Self {
            base_gravity: None,
            speed_multiplier: None,
            meters_per_unit: None,
            max_slope_radians: None,
            standing: PoseParams {
                height: 72.0,
                radius: 16.0,
                viewheight: 60.0,
                speed: 173.5,
                sprint_speed: 260.0,
                low_speed: 120.0,
                low_acceleration: 2500.0,
                acceleration: 450.0,
                deceleration: 1250.0,
                sprint_acceleration: 100.0,
                sprint_deceleration: 1250.0,
            },
            crouching: PoseParams {
                height: 47.0,
                radius: 16.0,
                viewheight: 32.0,
                speed: 80.0,
                sprint_speed: 0.0,
                low_speed: -1.0,
                low_acceleration: -1.0,
                acceleration: 2500.0,
                deceleration: -1.0,
                sprint_acceleration: -1.0,
                sprint_deceleration: -1.0,
            },
            gravity_scale: 1.0,
            step_height: 22.0,
            jump_height: 56.0,
            air_speed: 60.0,
            air_acceleration: 500.0,
            air_friction: 0.0,
            sprint_start_delay: 0.2,
            sprint_start_duration: 0.8,
            sprint_start_fast_duration: 0.2,
            sprint_end_duration: 0.15,
            sprint_view_offset: -6.0,
            speed_scale_side: 1.0,
            speed_scale_back: 1.0,
            can_jump_while_crouched: false,
            anti_multi_jump_height_frac: 0.3,
            anti_multi_jump_time_min: 0.15,
            anti_multi_jump_time_max: 0.75,
            air_drag: 0.0,
            land_slowdown_duration: 1.0,
            land_slowdown_frac: 0.0,
            land_slowdown_time_power: 2.0,
            land_slowdown_height_min: 300.0,
            land_slowdown_height_max: 800.0,
            land_slowdown_no_sprint_frac: 0.7,
            mantle_height: 80.0,
            climb_height: 100.0,
            slide_enabled: true,
            sprint_enabled: true,
            crouch_enabled: true,
            automantle: true,
            climb_enabled: true,
            slide_required_start_speed: 200.0,
            slide_required_start_speed_air: 90.0,
            slide_speed_boost: 150.0,
            slide_speed_boost_cap: 400.0,
            slide_boost_cooldown: 2.0,
            slide_decel: 100.0,
            slide_want_to_stop_decel: 400.0,
            slide_velocity_decay: 0.7,
            slide_accel: 50.0,
            slide_jump_height: 50.0,
            slide_stop_speed: 125.0,
            slide_max_stop_speed: 350.0,
            slide_max_jump_speed: 350.0,
            slide_max_angle_dot: 0.6,
            slide_step_velocity_reduction: 10.0,
            slide_while_in_air: false,
            slide_auto_stand: false,
            jump_grace_period: 0.2,
            skip_time: 1.0,
            skip_speed_reduce: 100.0,
            skip_speed_retain: -1.0,
            skip_jump_height_speed: 450.0,
            skip_jump_height_fraction: 1.0,
            extra_air_acceleration: 2.0,
            skin: 0.02,
            collision_iterations: 8,
            ledge_probe_distance: 24.0,
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ParamsError(pub &'static str);
impl fmt::Display for ParamsError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.0)
    }
}
impl Error for ParamsError {}

impl MoveParams {
    pub fn validate(&self) -> Result<(), ParamsError> {
        for (name, value) in [
            ("base_gravity 待定", self.base_gravity),
            ("speed_multiplier 待定", self.speed_multiplier),
            ("meters_per_unit 待定", self.meters_per_unit),
        ] {
            if !value.is_some_and(|v| v.is_finite() && v > 0.0) {
                return Err(ParamsError(name));
            }
        }
        if !self
            .max_slope_radians
            .is_some_and(|v| v.is_finite() && v > 0.0 && v < std::f32::consts::FRAC_PI_2)
        {
            return Err(ParamsError("max_slope_radians 待定或非法"));
        }
        for pose in [self.standing, self.crouching] {
            if ![
                pose.height,
                pose.radius,
                pose.viewheight,
                pose.low_speed,
                pose.low_acceleration,
                pose.speed,
                pose.sprint_speed,
                pose.acceleration,
                pose.deceleration,
                pose.sprint_acceleration,
                pose.sprint_deceleration,
            ]
            .iter()
            .all(|v| v.is_finite())
                || pose.radius <= 0.0
                || pose.height < 2.0 * pose.radius
                || pose.speed < 0.0
                || pose.sprint_speed < 0.0
                || pose.acceleration < 0.0
            {
                return Err(ParamsError("invalid pose settings"));
            }
        }
        if self.standing.deceleration < 0.0
            || self.standing.sprint_acceleration < 0.0
            || self.standing.sprint_deceleration < 0.0
        {
            return Err(ParamsError("invalid standing acceleration/deceleration"));
        }
        let values = [
            self.gravity_scale,
            self.step_height,
            self.jump_height,
            self.air_speed,
            self.air_acceleration,
            self.air_friction,
            self.sprint_start_delay,
            self.mantle_height,
            self.climb_height,
            self.slide_required_start_speed,
            self.slide_required_start_speed_air,
            self.slide_speed_boost,
            self.slide_speed_boost_cap,
            self.slide_boost_cooldown,
            self.slide_decel,
            self.slide_want_to_stop_decel,
            self.slide_accel,
            self.slide_jump_height,
            self.slide_stop_speed,
            self.slide_max_stop_speed,
            self.slide_max_jump_speed,
            self.slide_step_velocity_reduction,
            self.ledge_probe_distance,
            self.speed_scale_side,
            self.speed_scale_back,
            self.anti_multi_jump_height_frac,
            self.anti_multi_jump_time_min,
            self.anti_multi_jump_time_max,
            self.air_drag,
            self.land_slowdown_duration,
            self.land_slowdown_frac,
            self.land_slowdown_time_power,
            self.land_slowdown_height_min,
            self.land_slowdown_height_max,
            self.land_slowdown_no_sprint_frac,
            self.jump_grace_period,
            self.skip_time,
            self.skip_speed_reduce,
            self.skip_jump_height_speed,
            self.skip_jump_height_fraction,
            self.extra_air_acceleration,
        ];
        if values.iter().any(|v| !v.is_finite() || *v < 0.0)
            || self.gravity_scale <= 0.0
            || !self.skin.is_finite()
            || self.skin <= 0.0
            || !self.slide_velocity_decay.is_finite()
            || self.slide_velocity_decay <= 0.0
            || self.slide_velocity_decay > 1.0
            || !self.skip_speed_retain.is_finite()
            || !self.slide_max_angle_dot.is_finite()
            || self.land_slowdown_height_max <= self.land_slowdown_height_min
            || self.collision_iterations == 0
            || [
                self.sprint_start_duration,
                self.sprint_start_fast_duration,
                self.sprint_end_duration,
            ]
            .iter()
            .any(|v| !v.is_finite() || *v <= 0.0)
            || !self.sprint_view_offset.is_finite()
        {
            return Err(ParamsError("invalid movement/collision settings"));
        }
        if !self.gravity().is_finite() {
            return Err(ParamsError("gravity overflow"));
        }
        Ok(())
    }

    pub fn gravity(&self) -> f32 {
        self.base_gravity.unwrap_or(f32::NAN) * self.gravity_scale
    }
    pub fn to_meters(&self, raw: super::Vec3) -> Result<super::Vec3, ParamsError> {
        self.meters_per_unit
            .filter(|v| v.is_finite() && *v > 0.0)
            .map(|scale| raw * scale)
            .ok_or(ParamsError("meters_per_unit 待定"))
    }
    pub fn from_meters(&self, meters: super::Vec3) -> Result<super::Vec3, ParamsError> {
        self.meters_per_unit
            .filter(|v| v.is_finite() && *v > 0.0)
            .map(|scale| meters / scale)
            .ok_or(ParamsError("meters_per_unit 待定"))
    }
}
