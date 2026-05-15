use pyo3::prelude::*;
use pyo3::types::PyAnyMethods;

type FrameStateTuple = (f32, f32, bool, f32, f32, f32, Vec<(f32, f32, f32, f32)>);
type SpringStateTuple = (f32, f32, f32);
type ClickRippleTuple = (f32, f32, i32);
type RuntimeStateTuple = (
    i32,
    f32,
    f32,
    usize,
    bool,
    SpringStateTuple,
    SpringStateTuple,
    SpringStateTuple,
    Vec<ClickRippleTuple>,
);

#[derive(Clone, Debug)]
pub struct MouseEvent {
    pub t: Option<f64>,
    pub x: f32,
    pub y: f32,
    pub click: bool,
    pub region_x: Option<f32>,
    pub region_y: Option<f32>,
}

impl<'py> FromPyObject<'py> for MouseEvent {
    fn extract_bound(obj: &Bound<'py, PyAny>) -> PyResult<Self> {
        let t = match obj.get_item("t") {
            Ok(value) => Some(value.extract::<f64>()?),
            Err(_) => None,
        };
        let x = obj.get_item("x")?.extract::<f32>()?;
        let y = obj.get_item("y")?.extract::<f32>()?;
        let click = match obj.get_item("click") {
            Ok(value) => value.extract::<bool>()?,
            Err(_) => false,
        };
        let region_x = match obj.get_item("region_x") {
            Ok(value) => Some(value.extract::<f32>()?),
            Err(_) => None,
        };
        let region_y = match obj.get_item("region_y") {
            Ok(value) => Some(value.extract::<f32>()?),
            Err(_) => None,
        };

        Ok(Self {
            t,
            x,
            y,
            click,
            region_x,
            region_y,
        })
    }
}

#[derive(Clone, Debug)]
struct SpringState {
    value: f32,
    target: f32,
    velocity: f32,
    stiffness: f32,
    damping: f32,
    mass: f32,
}

impl SpringState {
    fn new(value: f32, stiffness: f32, damping: f32, mass: f32) -> Self {
        Self {
            value,
            target: value,
            velocity: 0.0,
            stiffness,
            damping,
            mass,
        }
    }

    fn set_target(&mut self, target: f32) {
        self.target = target;
    }

    fn update(&mut self, dt: f32) -> f32 {
        let force = -self.stiffness * (self.value - self.target) - self.damping * self.velocity;
        let acceleration = force / self.mass;
        self.velocity += acceleration * dt;
        self.value += self.velocity * dt;
        self.value
    }
}

#[derive(Clone, Debug)]
struct ClickRipple {
    x: f32,
    y: f32,
    life: i32,
}

#[derive(Clone, Debug)]
struct SegmentState {
    click_timer: i32,
    last_click_focus_x: f32,
    last_click_focus_y: f32,
    mouse_idx: usize,
    last_click_state: bool,
}

#[pyclass]
pub struct FrameStateEngine {
    base_zoom: f32,
    click_zoom: f32,
    click_duration: f32,
    source_fps: f32,
    width: f32,
    height: f32,
    dpi_scale_x: f32,
    dpi_scale_y: f32,
    mouse_events: Vec<MouseEvent>,
    has_timestamps: bool,
    spring_zoom: SpringState,
    spring_cam_x: SpringState,
    spring_cam_y: SpringState,
    segment_state: SegmentState,
    clicks: Vec<ClickRipple>,
}

#[pymethods]
impl FrameStateEngine {
    #[new]
    fn new(
        base_zoom: f32,
        click_zoom: f32,
        click_duration: f32,
        source_fps: f32,
        width: u32,
        height: u32,
        dpi_scale_x: f32,
        dpi_scale_y: f32,
        mouse_events: Vec<MouseEvent>,
    ) -> Self {
        let width_f = width as f32;
        let height_f = height as f32;
        let base_zoom = base_zoom.max(1.0);
        let click_zoom = click_zoom.max(base_zoom);
        let has_timestamps = mouse_events
            .first()
            .map(|event| event.t.is_some())
            .unwrap_or(false);

        Self {
            base_zoom,
            click_zoom,
            click_duration,
            source_fps,
            width: width_f,
            height: height_f,
            dpi_scale_x,
            dpi_scale_y,
            mouse_events,
            has_timestamps,
            spring_zoom: SpringState::new(base_zoom, 150.0, 25.0, 2.0),
            spring_cam_x: SpringState::new(0.0, 100.0, 20.0, 2.0),
            spring_cam_y: SpringState::new(0.0, 100.0, 20.0, 2.0),
            segment_state: SegmentState {
                click_timer: 0,
                last_click_focus_x: width_f / 2.0,
                last_click_focus_y: height_f / 2.0,
                mouse_idx: 0,
                last_click_state: false,
            },
            clicks: Vec::new(),
        }
    }

    fn reset_segment(&mut self, width: u32, height: u32) {
        self.width = width as f32;
        self.height = height as f32;
        self.spring_cam_x.value = self.width / 2.0;
        self.spring_cam_x.target = self.width / 2.0;
        self.spring_cam_y.value = self.height / 2.0;
        self.spring_cam_y.target = self.height / 2.0;
        self.spring_zoom.value = self.base_zoom;
        self.spring_zoom.target = self.base_zoom;
        self.segment_state = SegmentState {
            click_timer: 0,
            last_click_focus_x: self.width / 2.0,
            last_click_focus_y: self.height / 2.0,
            mouse_idx: 0,
            last_click_state: false,
        };
    }

    fn advance_batch(&mut self, frame_indices: Vec<u32>) -> (Vec<FrameStateTuple>, RuntimeStateTuple) {
        let mut states = Vec::with_capacity(frame_indices.len());
        for frame_idx in frame_indices {
            states.push(self.advance_one(frame_idx));
        }
        (states, self.export_runtime_state())
    }
}

impl FrameStateEngine {
    fn advance_one(&mut self, frame_idx: u32) -> FrameStateTuple {
        let dt = if self.source_fps > 0.0 {
            1.0 / self.source_fps
        } else {
            0.033
        };

        let (mouse_x, mouse_y, click) = self.resolve_mouse_state(frame_idx);
        let mut click_timer = self.segment_state.click_timer;
        let mut last_click_focus_x = self.segment_state.last_click_focus_x;
        let mut last_click_focus_y = self.segment_state.last_click_focus_y;

        let mut new_click_started = false;
        if click && !self.segment_state.last_click_state {
            new_click_started = true;
            click_timer = (self.source_fps * self.click_duration) as i32;
            last_click_focus_x = mouse_x;
            last_click_focus_y = mouse_y;
        }

        let target_zoom = if click_timer > 0 {
            click_timer -= 1;
            self.click_zoom
        } else {
            self.base_zoom
        };

        self.spring_zoom.set_target(target_zoom);
        let mut current_zoom = self.spring_zoom.update(dt);

        let mut snapped_to_one = false;
        if (target_zoom - self.base_zoom).abs() < f32::EPSILON
            && (current_zoom - self.base_zoom).abs() < 0.006
        {
            current_zoom = self.base_zoom;
            self.spring_zoom.value = self.base_zoom;
            self.spring_zoom.velocity = 0.0;
            snapped_to_one = true;
        }

        let vw = self.width / current_zoom;
        let vh = self.height / current_zoom;
        let (cam_x, cam_y) = if snapped_to_one {
            let cam_x = self.width / 2.0;
            let cam_y = self.height / 2.0;
            self.spring_cam_x.value = cam_x;
            self.spring_cam_x.target = cam_x;
            self.spring_cam_x.velocity = 0.0;
            self.spring_cam_y.value = cam_y;
            self.spring_cam_y.target = cam_y;
            self.spring_cam_y.velocity = 0.0;
            last_click_focus_x = cam_x;
            last_click_focus_y = cam_y;
            (cam_x, cam_y)
        } else if current_zoom > 1.01 {
            self.spring_cam_x.set_target(last_click_focus_x);
            self.spring_cam_y.set_target(last_click_focus_y);
            let cam_x = clamp(
                self.spring_cam_x.update(dt),
                vw / 2.0,
                self.width - vw / 2.0,
            );
            let cam_y = clamp(
                self.spring_cam_y.update(dt),
                vh / 2.0,
                self.height - vh / 2.0,
            );
            self.spring_cam_x.value = cam_x;
            self.spring_cam_y.value = cam_y;
            (cam_x, cam_y)
        } else {
            self.spring_cam_x.set_target(self.width / 2.0);
            self.spring_cam_y.set_target(self.height / 2.0);
            let cam_x = clamp(
                self.spring_cam_x.update(dt),
                vw / 2.0,
                self.width - vw / 2.0,
            );
            let cam_y = clamp(
                self.spring_cam_y.update(dt),
                vh / 2.0,
                self.height - vh / 2.0,
            );
            self.spring_cam_x.value = cam_x;
            self.spring_cam_y.value = cam_y;
            (cam_x, cam_y)
        };

        if new_click_started {
            self.clicks.push(ClickRipple {
                x: mouse_x,
                y: mouse_y,
                life: 20,
            });
        }

        let mut current_frame_clicks = Vec::new();
        let mut active_clicks = Vec::with_capacity(self.clicks.len());
        for mut ripple in self.clicks.drain(..) {
            if ripple.life > 0 {
                let radius = (20 - ripple.life) as f32 * 2.0;
                let alpha = ripple.life as f32 / 20.0;
                current_frame_clicks.push((ripple.x, ripple.y, radius, alpha));
                ripple.life -= 1;
                active_clicks.push(ripple);
            }
        }
        self.clicks = active_clicks;

        self.segment_state.click_timer = click_timer;
        self.segment_state.last_click_focus_x = last_click_focus_x;
        self.segment_state.last_click_focus_y = last_click_focus_y;
        self.segment_state.last_click_state = click;

        (
            mouse_x,
            mouse_y,
            click,
            current_zoom,
            cam_x,
            cam_y,
            current_frame_clicks,
        )
    }

    fn resolve_mouse_state(&mut self, frame_idx: u32) -> (f32, f32, bool) {
        if self.mouse_events.is_empty() {
            return (self.width / 2.0, self.height / 2.0, false);
        }

        let event = if self.has_timestamps {
            let current_time = frame_idx as f64 / self.source_fps.max(0.0001) as f64;
            while self.segment_state.mouse_idx < self.mouse_events.len() - 1
                && self.mouse_events[self.segment_state.mouse_idx]
                    .t
                    .unwrap_or(current_time)
                    < current_time
            {
                self.segment_state.mouse_idx += 1;
            }
            &self.mouse_events[self.segment_state.mouse_idx]
        } else if (frame_idx as usize) < self.mouse_events.len() {
            &self.mouse_events[frame_idx as usize]
        } else {
            &self.mouse_events[self.mouse_events.len() - 1]
        };

        let mut mouse_x = event.x * self.dpi_scale_x;
        let mut mouse_y = event.y * self.dpi_scale_y;
        if let Some(region_x) = event.region_x {
            mouse_x -= region_x * self.dpi_scale_x;
        }
        if let Some(region_y) = event.region_y {
            mouse_y -= region_y * self.dpi_scale_y;
        }

        let click = if self.has_timestamps || (frame_idx as usize) < self.mouse_events.len() {
            event.click
        } else {
            false
        };

        (mouse_x, mouse_y, click)
    }

    fn export_runtime_state(&self) -> RuntimeStateTuple {
        (
            self.segment_state.click_timer,
            self.segment_state.last_click_focus_x,
            self.segment_state.last_click_focus_y,
            self.segment_state.mouse_idx,
            self.segment_state.last_click_state,
            (
                self.spring_zoom.value,
                self.spring_zoom.target,
                self.spring_zoom.velocity,
            ),
            (
                self.spring_cam_x.value,
                self.spring_cam_x.target,
                self.spring_cam_x.velocity,
            ),
            (
                self.spring_cam_y.value,
                self.spring_cam_y.target,
                self.spring_cam_y.velocity,
            ),
            self.clicks
                .iter()
                .map(|click| (click.x, click.y, click.life))
                .collect(),
        )
    }
}

fn clamp(value: f32, min_value: f32, max_value: f32) -> f32 {
    value.max(min_value).min(max_value)
}
