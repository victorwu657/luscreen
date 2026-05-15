use log::info;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::Instant;
use windows::Win32::UI::WindowsAndMessaging::GetCursorPos;
use windows::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
use windows::Win32::Foundation::POINT;
use serde::{Serialize, Deserialize};
use windows_capture::{
    capture::{Context, GraphicsCaptureApiHandler},
    encoder::{
        AudioSettingsBuilder, ContainerSettingsBuilder, VideoEncoder, VideoSettingsBuilder,
    },
    frame::Frame,
    graphics_capture_api::InternalCaptureControl,
    monitor::Monitor,
    settings::{
        ColorFormat, CursorCaptureSettings, DirtyRegionSettings, DrawBorderSettings,
        MinimumUpdateIntervalSettings, SecondaryWindowSettings, Settings,
    },
};

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct MouseData {
    pub t: f64,
    pub x: i32,
    pub y: i32,
    pub click: bool,
}

#[derive(Clone, Copy, Debug)]
pub struct CaptureRegion {
    pub left: u32,
    pub top: u32,
    pub width: u32,
    pub height: u32,
}

impl CaptureRegion {
    fn right(self) -> u32 {
        self.left.saturating_add(self.width)
    }

    fn bottom(self) -> u32 {
        self.top.saturating_add(self.height)
    }
}

fn encode_ready_region_buffer(
    buffer: &[u8],
    width: u32,
    height: u32,
    color_format: ColorFormat,
) -> Result<Vec<u8>, Box<dyn std::error::Error + Send + Sync>> {
    let row_bytes = (width as usize) * 4;
    let expected_len = row_bytes * (height as usize);
    if buffer.len() != expected_len {
        return Err(format!(
            "cropped buffer size mismatch: got {}, expected {}",
            buffer.len(),
            expected_len
        )
        .into());
    }

    let mut out = vec![0u8; expected_len];
    for src_y in 0..(height as usize) {
        let src_row = &buffer[src_y * row_bytes..(src_y + 1) * row_bytes];
        let dst_y = (height as usize) - 1 - src_y;
        let dst_row = &mut out[dst_y * row_bytes..(dst_y + 1) * row_bytes];
        match color_format {
            ColorFormat::Rgba8 => {
                for x in 0..(width as usize) {
                    let src = x * 4;
                    let dst = x * 4;
                    dst_row[dst] = src_row[src + 2];
                    dst_row[dst + 1] = src_row[src + 1];
                    dst_row[dst + 2] = src_row[src];
                    dst_row[dst + 3] = src_row[src + 3];
                }
            }
            ColorFormat::Bgra8 => {
                dst_row.copy_from_slice(src_row);
            }
            other => {
                return Err(format!("unsupported color format for region capture: {:?}", other).into());
            }
        }
    }
    Ok(out)
}

pub struct Capture {
    encoder: Option<VideoEncoder>,
    start: Instant,
    frame_count: u64,
    stop_signal: Arc<AtomicBool>,
    mouse_storage: Arc<Mutex<Vec<MouseData>>>,
    capture_region: Option<CaptureRegion>,
}

impl GraphicsCaptureApiHandler for Capture {
    type Flags = (
        u32,
        u32,
        String,
        Arc<AtomicBool>,
        Arc<Mutex<Vec<MouseData>>>,
        Option<CaptureRegion>,
    ); // Width, Height, Filename, StopSignal, MouseStorage, CaptureRegion
    type Error = Box<dyn std::error::Error + Send + Sync>;

    fn new(ctx: Context<Self::Flags>) -> Result<Self, Self::Error> {
        let (width, height, filename, stop_signal, mouse_storage, capture_region) = ctx.flags;
        info!("Capture started with resolution: {}x{}, saving to: {}", width, height, filename);
        if let Some(region) = capture_region {
            info!(
                "Capture region enabled: left={} top={} width={} height={}",
                region.left, region.top, region.width, region.height
            );
        }
        
        // Initialize video encoder
        let encoder = VideoEncoder::new(
            VideoSettingsBuilder::new(width, height),
            AudioSettingsBuilder::default().disabled(true),
            ContainerSettingsBuilder::default(),
            &filename,
        )?;

        Ok(Self {
            encoder: Some(encoder),
            start: Instant::now(),
            frame_count: 0,
            stop_signal,
            mouse_storage,
            capture_region,
        })
    }

    fn on_frame_arrived(
        &mut self,
        frame: &mut Frame,
        capture_control: InternalCaptureControl,
    ) -> Result<(), Self::Error> {
        // Check for external stop signal FIRST
        if self.stop_signal.load(Ordering::Relaxed) {
            info!("Stop signal received. Stopping capture.");
            
            // Finish encoding
            if let Some(encoder) = self.encoder.take() {
                encoder.finish()?;
                info!("Video saved successfully.");
            }
            
            capture_control.stop();
            return Ok(());
        }

        self.frame_count += 1;
        
        // Capture mouse data
        let mut point = POINT::default();
        let mut x = 0;
        let mut y = 0;
        let mut click = false;
        
        unsafe {
            if GetCursorPos(&mut point).is_ok() {
                x = point.x;
                y = point.y;
            }
            // Check left mouse button (VK_LBUTTON = 0x01)
            // 0x8000 checks if the key is currently down
            if (GetAsyncKeyState(0x01) as u16 & 0x8000) != 0 {
                click = true;
            }
        }

        let elapsed = self.start.elapsed().as_secs_f64();
        let data = MouseData {
            t: elapsed,
            x,
            y,
            click,
        };

        // Push to storage
        if let Ok(mut storage) = self.mouse_storage.lock() {
            storage.push(data);
        }
        
        // Send frame to encoder
        if let Some(encoder) = &mut self.encoder {
            if let Some(region) = self.capture_region {
                let timestamp = frame.timestamp().Duration;
                let color_format = frame.color_format();
                let mut cropped = frame.buffer_crop(
                    region.left,
                    region.top,
                    region.right(),
                    region.bottom(),
                )?;
                let buffer = cropped.as_nopadding_buffer()?;
                let encoded = encode_ready_region_buffer(
                    buffer,
                    region.width,
                    region.height,
                    color_format,
                )?;
                encoder.send_frame_buffer(&encoded, timestamp)?;
            } else {
                encoder.send_frame(frame)?;
            }
        }

        // Log every 60 frames
        if self.frame_count % 60 == 0 {
            info!("Captured and encoded {} frames", self.frame_count);
        }

        // Check for external stop signal (Moved to top)

        Ok(())
    }

    fn on_closed(&mut self) -> Result<(), Self::Error> {
        info!("Capture session ended");
        Ok(())
    }
}

pub fn start_capture(
    filename: String,
    stop_signal: Arc<AtomicBool>,
    mouse_storage: Arc<Mutex<Vec<MouseData>>>,
    capture_region: Option<CaptureRegion>,
) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Initialize logger if not already initialized
    let _ = env_logger::try_init();

    let primary_monitor = Monitor::primary()?;
    let monitor_width = primary_monitor.width()?;
    let monitor_height = primary_monitor.height()?;

    let capture_region = capture_region.map(|region| CaptureRegion {
        left: region.left.min(monitor_width.saturating_sub(1)),
        top: region.top.min(monitor_height.saturating_sub(1)),
        width: region
            .width
            .max(2)
            .min(monitor_width.saturating_sub(region.left.min(monitor_width.saturating_sub(1)))),
        height: region
            .height
            .max(2)
            .min(monitor_height.saturating_sub(region.top.min(monitor_height.saturating_sub(1)))),
    });
    let width = capture_region.map(|region| region.width).unwrap_or(monitor_width);
    let height = capture_region.map(|region| region.height).unwrap_or(monitor_height);
    
    let settings = Settings::new(
        primary_monitor,
        CursorCaptureSettings::Default,
        DrawBorderSettings::Default,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Rgba8,
        (width, height, filename, stop_signal, mouse_storage, capture_region), // Pass flags
    );

    Capture::start(settings)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::encode_ready_region_buffer;
    use windows_capture::settings::ColorFormat;

    #[test]
    fn region_buffer_is_flipped_and_channel_swapped_for_rgba8() {
        let input = vec![
            1, 2, 3, 255, 4, 5, 6, 255,
            7, 8, 9, 255, 10, 11, 12, 255,
        ];
        let out = encode_ready_region_buffer(&input, 2, 2, ColorFormat::Rgba8).unwrap();
        assert_eq!(
            out,
            vec![
                9, 8, 7, 255, 12, 11, 10, 255,
                3, 2, 1, 255, 6, 5, 4, 255,
            ]
        );
    }

    #[test]
    fn region_buffer_is_flipped_only_for_bgra8() {
        let input = vec![
            1, 2, 3, 255, 4, 5, 6, 255,
            7, 8, 9, 255, 10, 11, 12, 255,
        ];
        let out = encode_ready_region_buffer(&input, 2, 2, ColorFormat::Bgra8).unwrap();
        assert_eq!(
            out,
            vec![
                7, 8, 9, 255, 10, 11, 12, 255,
                1, 2, 3, 255, 4, 5, 6, 255,
            ]
        );
    }
}
