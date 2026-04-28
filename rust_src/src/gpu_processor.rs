use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyList};
use pyo3::buffer::PyBuffer;
use wgpu::util::DeviceExt;
use std::sync::Arc;
use bytemuck::{Pod, Zeroable};

#[repr(C)]
#[derive(Copy, Clone, Debug, Pod, Zeroable)]
struct GlobalUniforms {
    target_width: u32,
    target_height: u32,
    bg_padding_ratio: f32,
    video_corner_radius_ratio: f32,
    watermark_x: i32,
    watermark_y: i32,
    has_watermark: u32,
    has_cursor: u32,
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Pod, Zeroable)]
struct FrameParams {
    zoom: f32,
    cam_x: f32,
    cam_y: f32,
    mouse_x: f32,
    mouse_y: f32,
    src_width: u32,
    src_height: u32,
    click_count: u32,
}

#[repr(C)]
#[derive(Copy, Clone, Debug, Pod, Zeroable)]
struct ClickParams {
    x: f32,
    y: f32,
    radius: f32,
    alpha: f32,
}

#[pyclass]
pub struct GpuProcessor {
    device: Arc<wgpu::Device>,
    queue: Arc<wgpu::Queue>,
    pipeline: wgpu::ComputePipeline,
    global_uniform_buffer: wgpu::Buffer,
    bg_texture_view: wgpu::TextureView,
    cursor_texture_view: wgpu::TextureView,
    watermark_texture_view: wgpu::TextureView,
    target_width: u32,
    target_height: u32,
    bind_group_layout_0: wgpu::BindGroupLayout,
    bind_group_layout_1: wgpu::BindGroupLayout,
    
    src_buffer: wgpu::Buffer,
    output_buffer: wgpu::Buffer,
    params_buffer: wgpu::Buffer,
    clicks_buffer: wgpu::Buffer,
    staging_buffer: wgpu::Buffer,
}

#[pymethods]
impl GpuProcessor {
    #[new]
    #[pyo3(signature = (target_width, target_height, bg_image_bytes=None, cursor_bytes=None, cursor_width=0, cursor_height=0, watermark_bytes=None, watermark_width=0, watermark_height=0, watermark_x=0, watermark_y=0, bg_padding_ratio=0.1, video_corner_radius_ratio=0.0))]
    fn new(
        target_width: u32,
        target_height: u32,
        bg_image_bytes: Option<Vec<u8>>,
        cursor_bytes: Option<Vec<u8>>,
        cursor_width: u32,
        cursor_height: u32,
        watermark_bytes: Option<Vec<u8>>,
        watermark_width: u32,
        watermark_height: u32,
        watermark_x: i32,
        watermark_y: i32,
        bg_padding_ratio: f32,
        video_corner_radius_ratio: f32,
    ) -> PyResult<Self> {
        let instance = wgpu::Instance::default();
        let adapter = pollster::block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
            power_preference: wgpu::PowerPreference::HighPerformance,
            force_fallback_adapter: false,
            compatible_surface: None,
        }))
        .ok_or_else(|| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>("Failed to find a GPU adapter"))?;

        let mut required_limits = wgpu::Limits::default();
        required_limits.max_buffer_size = 1024 * 1024 * 1024;
        required_limits.max_storage_buffer_binding_size = 1024 * 1024 * 1024;
        let adapter_limits = adapter.limits();
        required_limits.max_buffer_size = required_limits.max_buffer_size.min(adapter_limits.max_buffer_size);
        required_limits.max_storage_buffer_binding_size = required_limits.max_storage_buffer_binding_size.min(adapter_limits.max_storage_buffer_binding_size);

        let (device, queue) = pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("GpuProcessor Device"),
                required_features: wgpu::Features::empty(),
                required_limits,
                memory_hints: wgpu::MemoryHints::Performance,
            },
            None,
        ))
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyRuntimeError, _>(format!("Failed to create GPU device: {}", e)))?;

        let device = Arc::new(device);
        let queue = Arc::new(queue);

        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Composition Shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("shaders/composition.wgsl").into()),
        });

        let global_uniforms = GlobalUniforms {
            target_width, target_height, bg_padding_ratio, video_corner_radius_ratio,
            watermark_x, watermark_y,
            has_watermark: if watermark_bytes.is_some() { 1 } else { 0 },
            has_cursor: if cursor_bytes.is_some() { 1 } else { 0 },
        };
        let global_uniform_buffer = device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
            label: Some("Global Uniform Buffer"),
            contents: bytemuck::cast_slice(&[global_uniforms]),
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        });

        // Assets
        let mut bg_rgba = vec![255u8; (target_width * target_height * 4) as usize];
        if let Some(bg_bgr) = bg_image_bytes {
            for i in 0..(target_width * target_height) as usize {
                bg_rgba[i*4] = bg_bgr[i*3+2]; bg_rgba[i*4+1] = bg_bgr[i*3+1]; bg_rgba[i*4+2] = bg_bgr[i*3]; bg_rgba[i*4+3] = 255;
            }
        }
        let bg_texture = device.create_texture_with_data(&queue, &wgpu::TextureDescriptor {
            label: Some("BG Texture"),
            size: wgpu::Extent3d { width: target_width, height: target_height, depth_or_array_layers: 1 },
            mip_level_count: 1, sample_count: 1, dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm, usage: wgpu::TextureUsages::TEXTURE_BINDING, view_formats: &[],
        }, wgpu::util::TextureDataOrder::LayerMajor, &bg_rgba);
        let bg_texture_view = bg_texture.create_view(&Default::default());

        let cursor_rgba = cursor_bytes.unwrap_or_else(|| vec![0u8; 4]);
        let cursor_tex = device.create_texture_with_data(&queue, &wgpu::TextureDescriptor {
            label: Some("Cursor Texture"),
            size: wgpu::Extent3d { width: cursor_width.max(1), height: cursor_height.max(1), depth_or_array_layers: 1 },
            mip_level_count: 1, sample_count: 1, dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm, usage: wgpu::TextureUsages::TEXTURE_BINDING, view_formats: &[],
        }, wgpu::util::TextureDataOrder::LayerMajor, &cursor_rgba);
        let cursor_texture_view = cursor_tex.create_view(&Default::default());

        let wm_rgba = watermark_bytes.unwrap_or_else(|| vec![0u8; 4]);
        let wm_tex = device.create_texture_with_data(&queue, &wgpu::TextureDescriptor {
            label: Some("WM Texture"),
            size: wgpu::Extent3d { width: watermark_width.max(1), height: watermark_height.max(1), depth_or_array_layers: 1 },
            mip_level_count: 1, sample_count: 1, dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8Unorm, usage: wgpu::TextureUsages::TEXTURE_BINDING, view_formats: &[],
        }, wgpu::util::TextureDataOrder::LayerMajor, &wm_rgba);
        let watermark_texture_view = wm_tex.create_view(&Default::default());

        let max_batch_size = 24usize;
        let max_pixels = 3840usize * 2160usize;
        
        let src_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Extreme Src Buffer"),
            size: (max_pixels * 3 * max_batch_size) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        // 核心优化：NV12 输出缓冲区大小为 1.5x
        let out_buffer_size = (target_width as usize * target_height as usize * 3 / 2 * max_batch_size) as u64;
        let output_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Extreme Output Buffer (NV12)"),
            size: out_buffer_size,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
            mapped_at_creation: false,
        });

        let params_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Extreme Params Buffer"),
            size: (std::mem::size_of::<FrameParams>() * max_batch_size) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let clicks_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Extreme Clicks Buffer"),
            size: (std::mem::size_of::<ClickParams>() * 100 * max_batch_size) as u64,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let staging_buffer = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Extreme Staging Buffer"),
            size: out_buffer_size,
            usage: wgpu::BufferUsages::MAP_READ | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });

        let bind_group_layout_0 = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("Params Layout"),
            entries: &[
                wgpu::BindGroupLayoutEntry { binding: 0, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Uniform, has_dynamic_offset: false, min_binding_size: None }, count: None },
                wgpu::BindGroupLayoutEntry { binding: 1, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Storage { read_only: true }, has_dynamic_offset: false, min_binding_size: None }, count: None },
                wgpu::BindGroupLayoutEntry { binding: 2, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Storage { read_only: true }, has_dynamic_offset: false, min_binding_size: None }, count: None },
            ],
        });

        let bind_group_layout_1 = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("Assets Layout"),
            entries: &[
                wgpu::BindGroupLayoutEntry { binding: 0, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Storage { read_only: true }, has_dynamic_offset: false, min_binding_size: None }, count: None },
                wgpu::BindGroupLayoutEntry { binding: 1, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Texture { sample_type: wgpu::TextureSampleType::Float { filterable: false }, view_dimension: wgpu::TextureViewDimension::D2, multisampled: false }, count: None },
                wgpu::BindGroupLayoutEntry { binding: 2, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Texture { sample_type: wgpu::TextureSampleType::Float { filterable: false }, view_dimension: wgpu::TextureViewDimension::D2, multisampled: false }, count: None },
                wgpu::BindGroupLayoutEntry { binding: 3, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Texture { sample_type: wgpu::TextureSampleType::Float { filterable: false }, view_dimension: wgpu::TextureViewDimension::D2, multisampled: false }, count: None },
                wgpu::BindGroupLayoutEntry { binding: 4, visibility: wgpu::ShaderStages::COMPUTE, ty: wgpu::BindingType::Buffer { ty: wgpu::BufferBindingType::Storage { read_only: false }, has_dynamic_offset: false, min_binding_size: None }, count: None },
            ],
        });

        let pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("Extreme Pipeline Layout"),
            bind_group_layouts: &[&bind_group_layout_0, &bind_group_layout_1],
            push_constant_ranges: &[],
        });

        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("Extreme Compute Pipeline"),
            layout: Some(&pipeline_layout),
            module: &shader,
            entry_point: "main",
            compilation_options: Default::default(),
            cache: None,
        });

        Ok(GpuProcessor {
            device, queue, pipeline, global_uniform_buffer,
            bg_texture_view, cursor_texture_view, watermark_texture_view,
            target_width, target_height, bind_group_layout_0, bind_group_layout_1,
            src_buffer, output_buffer, params_buffer, clicks_buffer, staging_buffer,
        })
    }

    fn process_batch(
        &self,
        py: Python<'_>,
        frames: &Bound<'_, PyList>,
        src_width: u32,
        src_height: u32,
        params: Vec<(f32, f32, f32, f32, f32)>,
        clicks_batch: Vec<Vec<(f32, f32, f32, f32)>>,
    ) -> PyResult<PyObject> {
        let batch_size = frames.len();
        let frame_in_size = (src_width * src_height * 3) as usize;
        let frame_out_size = (self.target_width as usize * self.target_height as usize * 3 / 2);

        for i in 0..batch_size {
            let item = frames.get_item(i)?;
            let buf: PyBuffer<u8> = PyBuffer::get_bound(&item)?;
            unsafe {
                let ptr = buf.buf_ptr() as *const u8;
                let slice = std::slice::from_raw_parts(ptr, frame_in_size);
                self.queue.write_buffer(&self.src_buffer, (i * frame_in_size) as u64, slice);
            }
        }

        let mut all_params = Vec::with_capacity(batch_size);
        let mut all_clicks = Vec::with_capacity(batch_size * 100);
        for i in 0..batch_size {
            let (zoom, cam_x, cam_y, mouse_x, mouse_y) = params[i];
            all_params.push(FrameParams { zoom, cam_x, cam_y, mouse_x, mouse_y, src_width, src_height, click_count: clicks_batch[i].len() as u32 });
            let mut frame_clicks: Vec<ClickParams> = clicks_batch[i].iter().map(|c| ClickParams { x: c.0, y: c.1, radius: c.2, alpha: c.3 }).collect();
            frame_clicks.resize(100, ClickParams { x: 0.0, y: 0.0, radius: 0.0, alpha: 0.0 });
            all_clicks.extend_from_slice(&frame_clicks);
        }
        self.queue.write_buffer(&self.params_buffer, 0, bytemuck::cast_slice(&all_params));
        self.queue.write_buffer(&self.clicks_buffer, 0, bytemuck::cast_slice(&all_clicks));

        let bind_group_0 = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None, layout: &self.bind_group_layout_0,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: self.global_uniform_buffer.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: self.params_buffer.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: self.clicks_buffer.as_entire_binding() },
            ],
        });

        let bind_group_1 = self.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None, layout: &self.bind_group_layout_1,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: self.src_buffer.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: wgpu::BindingResource::TextureView(&self.bg_texture_view) },
                wgpu::BindGroupEntry { binding: 2, resource: wgpu::BindingResource::TextureView(&self.cursor_texture_view) },
                wgpu::BindGroupEntry { binding: 3, resource: wgpu::BindingResource::TextureView(&self.watermark_texture_view) },
                wgpu::BindGroupEntry { binding: 4, resource: self.output_buffer.as_entire_binding() },
            ],
        });

        let mut encoder = self.device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: None });
        {
            let mut compute_pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor { label: None, timestamp_writes: None });
            compute_pass.set_pipeline(&self.pipeline);
            compute_pass.set_bind_group(0, &bind_group_0, &[]);
            compute_pass.set_bind_group(1, &bind_group_1, &[]);
            // 4x2 块处理，所以线程组除以 4 和 2
            compute_pass.dispatch_workgroups((self.target_width + 31) / 32, (self.target_height + 15) / 16, batch_size as u32);
        }

        encoder.copy_buffer_to_buffer(&self.output_buffer, 0, &self.staging_buffer, 0, (batch_size * frame_out_size) as u64);
        self.queue.submit(Some(encoder.finish()));

        let buffer_slice = self.staging_buffer.slice(0..(batch_size * frame_out_size) as u64);
        let (sender, receiver) = std::sync::mpsc::channel();
        buffer_slice.map_async(wgpu::MapMode::Read, move |v| sender.send(v).unwrap());
        self.device.poll(wgpu::Maintain::Wait);
        
        let mut result_bytes = Vec::with_capacity(batch_size * frame_out_size);
        if let Ok(Ok(())) = receiver.recv() {
            let data = buffer_slice.get_mapped_range();
            result_bytes.extend_from_slice(&data);
        }
        self.staging_buffer.unmap();

        Ok(PyBytes::new_bound(py, &result_bytes).into())
    }
}
