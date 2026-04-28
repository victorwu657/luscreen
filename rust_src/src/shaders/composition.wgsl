struct GlobalUniforms {
    target_width: u32,
    target_height: u32,
    bg_padding_ratio: f32,
    video_corner_radius_ratio: f32,
    watermark_x: i32,
    watermark_y: i32,
    has_watermark: u32,
    has_cursor: u32,
};

struct FrameParams {
    zoom: f32,
    cam_x: f32,
    cam_y: f32,
    mouse_x: f32,
    mouse_y: f32,
    src_width: u32,
    src_height: u32,
    click_count: u32,
};

struct ClickParams {
    x: f32,
    y: f32,
    radius: f32,
    alpha: f32,
};

@group(0) @binding(0) var<uniform> global: GlobalUniforms;
@group(0) @binding(1) var<storage, read> batch_params: array<FrameParams>;
@group(0) @binding(2) var<storage, read> batch_clicks: array<ClickParams>;

@group(1) @binding(0) var<storage, read> batch_src_buffer: array<u32>;
@group(1) @binding(1) var bg_tex: texture_2d<f32>;
@group(1) @binding(2) var cursor_tex: texture_2d<f32>;
@group(1) @binding(3) var watermark_tex: texture_2d<f32>;
@group(1) @binding(4) var<storage, read_write> batch_output_buffer: array<u32>;

fn get_yuv(rgb: vec3<f32>) -> vec3<f32> {
    // BT.601 Limited Range (Standard for H.264/NV12)
    let y = (0.257 * rgb.r + 0.504 * rgb.g + 0.098 * rgb.b) + 16.0/255.0;
    let u = (-0.148 * rgb.r - 0.291 * rgb.g + 0.439 * rgb.b) + 128.0/255.0;
    let v = (0.439 * rgb.r - 0.368 * rgb.g - 0.071 * rgb.b) + 128.0/255.0;
    return vec3<f32>(y, u, v);
}

fn fetch_pixel(frame_idx: u32, sx: u32, sy: u32, src_w: u32, src_h: u32) -> vec3<f32> {
    let frame_size = src_w * src_h * 3u;
    let pixel_off = (sy * src_w + sx) * 3u;
    let total_off = (frame_idx * frame_size) + pixel_off;
    
    let u32_idx = total_off / 4u;
    let shift = (total_off % 4u) * 8u;
    var val: u32;
    if (shift <= 8u) { 
        val = batch_src_buffer[u32_idx] >> shift; 
    } else { 
        val = (batch_src_buffer[u32_idx] >> shift) | (batch_src_buffer[u32_idx + 1u] << (32u - shift)); 
    }
    return vec3<f32>(
        f32((val >> 16u) & 0xFFu) / 255.0, 
        f32((val >> 8u) & 0xFFu) / 255.0, 
        f32(val & 0xFFu) / 255.0
    );
}

@compute @workgroup_size(8, 8, 1)
fn main(@builtin(global_invocation_id) global_id: vec3<u32>) {
    let base_x = global_id.x * 4u;
    let base_y = global_id.y * 2u;
    let frame_idx = global_id.z;
    let W = global.target_width;
    let H = global.target_height;

    if (base_x >= W || base_y >= H) { return; }

    var y_vals: array<u32, 8>;
    var u_sum0 = 0.0;
    var v_sum0 = 0.0;
    var u_sum1 = 0.0;
    var v_sum1 = 0.0;

    let params = batch_params[frame_idx];
    let vw = f32(params.src_width) / params.zoom;
    let vh = f32(params.src_height) / params.zoom;
    let x1 = max(0.0, params.cam_x - vw / 2.0);
    let y1 = max(0.0, params.cam_y - vh / 2.0);
    
    let padding_px = f32(W) * global.bg_padding_ratio;
    let avail_w = f32(W) - padding_px * 2.0;
    let avail_h = f32(H) - padding_px * 2.0;
    let source_aspect = f32(params.src_width) / f32(params.src_height);
    let target_aspect = avail_w / avail_h;
    
    var inner_w = avail_w; var inner_h = avail_h;
    var off_x = padding_px; var off_y = padding_px;
    if (source_aspect > target_aspect) {
        inner_h = avail_w / source_aspect;
        off_y = padding_px + (avail_h - inner_h) / 2.0;
    } else {
        inner_w = avail_h * source_aspect;
        off_x = padding_px + (avail_w - inner_w) / 2.0;
    }
    
    let inner_w_i = max(1.0, floor(inner_w + 0.5));
    let inner_h_i = max(1.0, floor(inner_h + 0.5));
    let off_x_i = floor(off_x + 0.5);
    let off_y_i = floor(off_y + 0.5);

    for (var dy = 0u; dy < 2u; dy = dy + 1u) {
        for (var dx = 0u; dx < 4u; dx = dx + 1u) {
            let x = base_x + dx;
            let y = base_y + dy;
            if (x >= W || y >= H) { continue; }

            var col = textureLoad(bg_tex, vec2<u32>(x, y), 0).rgb;
            let fx = f32(x); let fy = f32(y);
            let fx_c = fx + 0.5;
            let fy_c = fy + 0.5;

            if (fx_c >= off_x_i && fx_c < off_x_i + inner_w_i && fy_c >= off_y_i && fy_c < off_y_i + inner_h_i) {
                let radius = f32(W) * global.video_corner_radius_ratio;
                var in_video = true;
                
                if (radius > 0.0) {
                    let radius_i = floor(radius + 0.5);
                    let lx = fx_c - off_x_i;
                    let ly = fy_c - off_y_i;
                    if (lx < radius_i && ly < radius_i) {
                        if (distance(vec2<f32>(lx, ly), vec2<f32>(radius_i, radius_i)) > radius_i) { in_video = false; }
                    } else if (lx > inner_w_i - radius_i && ly < radius_i) {
                        if (distance(vec2<f32>(lx, ly), vec2<f32>(inner_w_i - radius_i, radius_i)) > radius_i) { in_video = false; }
                    } else if (lx < radius_i && ly > inner_h_i - radius_i) {
                        if (distance(vec2<f32>(lx, ly), vec2<f32>(radius_i, inner_h_i - radius_i)) > radius_i) { in_video = false; }
                    } else if (lx > inner_w_i - radius_i && ly > inner_h_i - radius_i) {
                        if (distance(vec2<f32>(lx, ly), vec2<f32>(inner_w_i - radius_i, inner_h_i - radius_i)) > radius_i) { in_video = false; }
                    }
                }

                if (in_video) {
                    let src_u = (fx_c - off_x_i) / inner_w_i;
                    let src_v = (fy_c - off_y_i) / inner_h_i;
                
                // 双线性插值 (Bilinear Interpolation) + 裁剪窗口应用
                let vw1 = max(1.0, vw - 1.0);
                let vh1 = max(1.0, vh - 1.0);
                let sx_px = x1 + src_u * vw1;
                let sy_px = y1 + src_v * vh1;
                
                let sx0 = u32(floor(sx_px));
                let sy0 = u32(floor(sy_px));
                let sx1 = min(sx0 + 1u, params.src_width - 1u);
                let sy1 = min(sy0 + 1u, params.src_height - 1u);
                
                let wx = fract(sx_px);
                let wy = fract(sy_px);
                
                let p00 = fetch_pixel(frame_idx, sx0, sy0, params.src_width, params.src_height);
                let p10 = fetch_pixel(frame_idx, sx1, sy0, params.src_width, params.src_height);
                let p01 = fetch_pixel(frame_idx, sx0, sy1, params.src_width, params.src_height);
                let p11 = fetch_pixel(frame_idx, sx1, sy1, params.src_width, params.src_height);
                
                col = mix(mix(p00, p10, wx), mix(p01, p11, wx), wy);

                // 点击波纹 (相对于视频内部坐标)
                let click_start_idx = frame_idx * 100u;
                for (var i = 0u; i < params.click_count; i = i + 1u) {
                    let click = batch_clicks[click_start_idx + i];
                    let dcx = (click.x - x1) * (inner_w_i / vw) + off_x_i;
                    let dcy = (click.y - y1) * (inner_h_i / vh) + off_y_i;
                    if (distance(vec2<f32>(fx, fy), vec2<f32>(dcx, dcy)) < click.radius) {
                        col = mix(col, vec3<f32>(1.0, 0.0, 0.0), click.alpha);
                    }
                }

                // 光标
                if (global.has_cursor == 1u) {
                    let draw_mx = (params.mouse_x - x1) * (inner_w_i / vw) + off_x_i;
                    let draw_my = (params.mouse_y - y1) * (inner_h_i / vh) + off_y_i;
                    let cur_size = textureDimensions(cursor_tex);
                    let cx = fx - draw_mx; let cy = fy - draw_my;
                    if (cx >= 0.0 && cx < f32(cur_size.x) && cy >= 0.0 && cy < f32(cur_size.y)) {
                        let cp = textureLoad(cursor_tex, vec2<u32>(u32(cx), u32(cy)), 0);
                        col = mix(col, cp.rgb, cp.a);
                    }
                }
            }
        }

        // 水印
            if (global.has_watermark == 1u) {
                let wx = fx - f32(global.watermark_x); let wy = fy - f32(global.watermark_y);
                let ws = textureDimensions(watermark_tex);
                if (wx >= 0.0 && wx < f32(ws.x) && wy >= 0.0 && wy < f32(ws.y)) {
                    let wp = textureLoad(watermark_tex, vec2<u32>(u32(wx), u32(wy)), 0);
                    col = mix(col, wp.rgb, wp.a);
                }
            }

            let yuv = get_yuv(col);
            y_vals[dy * 4u + dx] = u32(yuv.x * 255.0) & 0xFFu;
            if (dx < 2u) {
                u_sum0 += yuv.y; v_sum0 += yuv.z;
            } else {
                u_sum1 += yuv.y; v_sum1 += yuv.z;
            }
        }
    }

    let frame_start = frame_idx * (W * H * 3u / 2u);
    let y_idx0 = (frame_start + base_y * W + base_x) / 4u;
    let y_idx1 = (frame_start + (base_y + 1u) * W + base_x) / 4u;
    batch_output_buffer[y_idx0] = y_vals[0] | (y_vals[1] << 8u) | (y_vals[2] << 16u) | (y_vals[3] << 24u);
    batch_output_buffer[y_idx1] = y_vals[4] | (y_vals[5] << 8u) | (y_vals[6] << 16u) | (y_vals[7] << 24u);

    let uv_start = frame_start + (W * H);
    let u0 = u32((u_sum0 / 4.0) * 255.0) & 0xFFu;
    let v0 = u32((v_sum0 / 4.0) * 255.0) & 0xFFu;
    let u1 = u32((u_sum1 / 4.0) * 255.0) & 0xFFu;
    let v1 = u32((v_sum1 / 4.0) * 255.0) & 0xFFu;
    let uv_idx = (uv_start + (base_y / 2u) * W + base_x) / 4u;
    batch_output_buffer[uv_idx] = u0 | (v0 << 8u) | (u1 << 16u) | (v1 << 24u);
}
