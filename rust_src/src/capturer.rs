use log::{info, error};
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

pub struct Capture {
    encoder: Option<VideoEncoder>,
    start: Instant,
    frame_count: u64,
    stop_signal: Arc<AtomicBool>,
    mouse_storage: Arc<Mutex<Vec<MouseData>>>,
}

impl GraphicsCaptureApiHandler for Capture {
    type Flags = (u32, u32, String, Arc<AtomicBool>, Arc<Mutex<Vec<MouseData>>>); // Width, Height, Filename, StopSignal, MouseStorage
    type Error = Box<dyn std::error::Error + Send + Sync>;

    fn new(ctx: Context<Self::Flags>) -> Result<Self, Self::Error> {
        let (width, height, filename, stop_signal, mouse_storage) = ctx.flags;
        info!("Capture started with resolution: {}x{}, saving to: {}", width, height, filename);
        
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
            encoder.send_frame(frame)?;
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

pub fn start_capture(filename: String, stop_signal: Arc<AtomicBool>, mouse_storage: Arc<Mutex<Vec<MouseData>>>) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    // Initialize logger if not already initialized
    let _ = env_logger::try_init();

    let primary_monitor = Monitor::primary()?;
    let width = primary_monitor.width()?;
    let height = primary_monitor.height()?;
    
    let settings = Settings::new(
        primary_monitor,
        CursorCaptureSettings::Default,
        DrawBorderSettings::Default,
        SecondaryWindowSettings::Default,
        MinimumUpdateIntervalSettings::Default,
        DirtyRegionSettings::Default,
        ColorFormat::Rgba8,
        (width, height, filename, stop_signal, mouse_storage), // Pass flags
    );

    Capture::start(settings)?;
    Ok(())
}