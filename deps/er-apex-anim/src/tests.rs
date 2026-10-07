use super::*;
fn skeleton() -> Vec<Bone> {
    (0..231)
        .map(|i| Bone {
            name: format!("bone{i}"),
            parent: if i == 0 { None } else { Some(0) },
            rest: Trs {
                translation: [i as f32, 2., 3.],
                ..Trs::default()
            },
        })
        .collect()
}
fn clip() -> Clip {
    Clip {
        name: "test".into(),
        sequence: "test".into(),
        source_path: String::new(),
        rig: String::new(),
        guid: 1,
        fps: 2.,
        frame_count: 3,
        looping: true,
        additive: false,
        sample_index: 0,
        sample_count: 1,
        metadata_json: "{}".into(),
        events: vec![
            Event {
                frame: 0,
                name: "zero".into(),
                parameter: String::new(),
            },
            Event {
                frame: 1,
                name: "middle".into(),
                parameter: "sound".into(),
            },
            Event {
                frame: 2,
                name: "last".into(),
                parameter: String::new(),
            },
        ],
        root: None,
        tracks: vec![],
    }
}
fn pack(c: Clip) -> Pack {
    let bones = skeleton();
    let rest = bones.iter().map(|b| b.rest).collect();
    Pack {
        bones,
        rest,
        clips: vec![c],
    }
}
fn track() -> Track {
    Track {
        bone: 1,
        additive: false,
        weights: [1.; 3],
        translations: vec![[0., 0., 0.], [2., 4., 6.], [4., 8., 12.]],
        rotations: vec![[0., 0., 0., 1.], [0., 0., -1., 0.], [0., 0., 0., -1.]],
        scales: vec![],
    }
}
fn near(a: f32, b: f32) {
    assert!((a - b).abs() < 0.0002, "{a} != {b}");
}
#[test]
fn resets_all_bones_and_clamps() {
    let mut c = clip();
    c.tracks.push(track());
    let p = pack(c);
    let mut out = vec![Trs::default(); 231];
    p.sample(0, 0.25, false, &mut out).unwrap();
    assert_eq!(out[230], p.bones[230].rest);
    assert_eq!(out[1].translation, [1., 2., 3.]);
    near(out[1].rotation[2], -std::f32::consts::FRAC_1_SQRT_2);
    p.sample(0, 10., false, &mut out).unwrap();
    assert_eq!(out[1].translation, [4., 8., 12.]);
    p.sample(0, -1., false, &mut out).unwrap();
    assert_eq!(out[1].translation, [0.; 3]);
}
#[test]
fn shortest_path_and_exact_wrap() {
    let q = normalize([0.1, 0.2, 0.3, 0.9]);
    let r = slerp(q, q.map(|x| -x), 0.5);
    for i in 0..4 {
        near(q[i], r[i]);
    }
    let mut c = clip();
    c.tracks.push(track());
    let p = pack(c);
    let mut out = vec![Trs::default(); 231];
    p.sample(0, 1., true, &mut out).unwrap();
    assert_eq!(out[1].translation, [0.; 3]);
    p.sample(0, -0.75, true, &mut out).unwrap();
    assert_eq!(out[1].translation, [1., 2., 3.]);
}
#[test]
fn additive_weight_and_missing_channels_keep_input() {
    let mut c = clip();
    let mut t = track();
    t.additive = true;
    t.weights = [0.5, 0.5, 0.5];
    t.translations = vec![[2., 0., 0.]];
    t.rotations = vec![[0., 0., 1., 0.]];
    t.scales = vec![[2., 1., 1.]];
    c.tracks.push(t);
    c.additive = true;
    let p = pack(c);
    let mut out = vec![
        Trs {
            translation: [10.; 3],
            scale: [2.; 3],
            ..Trs::default()
        };
        231
    ];
    p.apply(0, 0., false, &mut out).unwrap();
    assert_eq!(out[1].translation, [11., 10., 10.]);
    assert_eq!(out[1].scale, [3., 2., 2.]);
    near(out[1].rotation[2], std::f32::consts::FRAC_1_SQRT_2);
    assert_eq!(out[230].translation, [10.; 3]);
}
#[test]
fn output_and_time_errors_do_not_modify_pose() {
    let p = pack(clip());
    let mut short = vec![Trs::default(); 230];
    assert_eq!(
        p.sample(0, 0., false, &mut short),
        Err(Error::OutputTooSmall)
    );
    let mut out = vec![Trs::default(); 231];
    assert_eq!(p.sample(1, 0., false, &mut out), Err(Error::InvalidClip));
    assert_eq!(
        p.sample(0, f64::NAN, false, &mut out),
        Err(Error::InvalidTime)
    );
    assert_eq!(
        p.root_motion_delta(0, 0., f64::INFINITY, true),
        Err(Error::InvalidTime)
    );
    assert_eq!(out[230], Trs::default());
}
#[test]
fn events_open_closed_multiple_wraps_and_zero() {
    let p = pack(clip());
    let e = p.events_between(0, 0., 2., true).unwrap();
    assert_eq!(
        e.iter().map(|e| e.time_s).collect::<Vec<_>>(),
        vec![0.5, 1., 1., 1.5, 2., 2.]
    );
    let initial = p.events_between(0, -0.0001, 0., false).unwrap();
    assert_eq!(initial[0].event.name, "zero");
    assert!(p.events_between(0, 0.5, 0.5, true).unwrap().is_empty());
    assert!(matches!(
        p.events_between(0, 1., 0., true),
        Err(Error::InvalidTime)
    ));
    assert!(matches!(
        p.events_between(0, 0., 1e7, true),
        Err(Error::TooManyEvents)
    ));
}
#[test]
fn root_separation_and_multiple_cycles_with_turn() {
    let mut c = clip();
    c.root = Some(RootTrack {
        bone: 0,
        translations: vec![[10., 0., 0.], [11., 0., 0.], [12., 0., 0.]],
        rotations: vec![
            [0., 0., 0., 1.],
            [0., 0., 0.38268343, 0.9238795],
            [0., 0., 0.70710677, 0.70710677],
        ],
    });
    let p = pack(c);
    let mut out = vec![Trs::default(); 231];
    p.sample(0, 0.5, false, &mut out).unwrap();
    assert_eq!(out[0].translation, [10., 0., 0.]);
    let d = p.root_motion_delta(0, 0., 2., true).unwrap();
    near(d.translation[0], 2.);
    near(d.translation[1], 2.);
    near(d.rotation[2].abs(), 1.);
    let reverse = p.root_motion_delta(0, 2., 0., true).unwrap();
    let identity = compose(d, reverse);
    for v in identity.translation {
        near(v, 0.);
    }
    let a = p.root_motion_delta(0, 0., 0.8, true).unwrap();
    let b = p.root_motion_delta(0, 0.8, 1.2, true).unwrap();
    let combined = compose(a, b);
    let whole = p.root_motion_delta(0, 0., 1.2, true).unwrap();
    for i in 0..3 {
        near(combined.translation[i], whole.translation[i]);
    }
}
fn string(b: &mut Vec<u8>, s: &str) {
    b.extend((s.len() as u16).to_le_bytes());
    b.extend(s.as_bytes());
}
fn floats(b: &mut Vec<u8>, v: &[f32]) {
    for f in v {
        b.extend(f.to_le_bytes());
    }
}
fn fixture() -> Vec<u8> {
    let mut payload = Vec::new();
    string(&mut payload, "root");
    payload.extend((-1_i32).to_le_bytes());
    floats(&mut payload, &[0., 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
    let mut c = Vec::new();
    for s in ["one", "one", "source", "rig"] {
        string(&mut c, s);
    }
    c.extend(1_u64.to_le_bytes());
    floats(&mut c, &[30.]);
    for v in [1_u32, 0, 0, 1, 0] {
        c.extend(v.to_le_bytes());
    }
    string(&mut c, "{}");
    c.extend((-1_i32).to_le_bytes());
    c.extend(0_u32.to_le_bytes());
    payload.extend((c.len() as u32).to_le_bytes());
    payload.extend(c);
    let mut b = b"FUSEANIM".to_vec();
    b.extend(0_u32.to_le_bytes());
    b.extend((32 + payload.len() as u64).to_le_bytes());
    b.extend(1_u32.to_le_bytes());
    b.extend(1_u32.to_le_bytes());
    b.extend(crc32(&payload).to_le_bytes());
    b.extend(payload);
    b
}
fn repair(b: &mut [u8]) {
    let crc = crc32(&b[32..]);
    b[28..32].copy_from_slice(&crc.to_le_bytes());
}
#[test]
fn parser_valid_fixture_and_every_truncation() {
    let b = fixture();
    let p = Pack::parse(&b).unwrap();
    assert_eq!(p.clip_by_name("one"), Some(0));
    for n in 0..b.len() {
        assert!(Pack::parse(&b[..n]).is_err());
    }
}
#[test]
fn rejects_bad_crc_parent_utf8_nonfinite_and_counts() {
    let b = fixture();
    let mut corrupt = b.clone();
    corrupt[40] ^= 1;
    assert!(matches!(
        Pack::parse(&corrupt),
        Err(Error::ChecksumMismatch)
    ));
    let mut parent = b.clone();
    parent[38..42].copy_from_slice(&0_i32.to_le_bytes());
    repair(&mut parent);
    assert!(matches!(
        Pack::parse(&parent),
        Err(Error::InvalidData("bone parent"))
    ));
    let mut utf = b.clone();
    utf[34] = 255;
    repair(&mut utf);
    assert!(matches!(
        Pack::parse(&utf),
        Err(Error::InvalidData("UTF-8"))
    ));
    let mut nan = b.clone();
    nan[42..46].copy_from_slice(&f32::NAN.to_le_bytes());
    repair(&mut nan);
    assert!(matches!(
        Pack::parse(&nan),
        Err(Error::InvalidData("nonfinite float"))
    ));
    let mut counts = b.clone();
    counts[20..24].copy_from_slice(&u32::MAX.to_le_bytes());
    assert!(matches!(
        Pack::parse(&counts),
        Err(Error::InvalidData("bone count"))
    ));
}
#[test]
fn corrupted_payload_with_repaired_crc_never_panics() {
    let b = fixture();
    for i in 32..b.len() {
        for x in [0_u8, 0xff, 0x80] {
            let mut m = b.clone();
            m[i] = x;
            repair(&mut m);
            let _ = Pack::parse(&m);
        }
    }
}
#[test]
fn one_frame_and_no_root() {
    let mut c = clip();
    c.frame_count = 1;
    c.events.truncate(1);
    let p = pack(c);
    let mut out = vec![Trs::default(); 231];
    p.sample(0, 100., true, &mut out).unwrap();
    assert_eq!(out[230], p.bones[230].rest);
    assert_eq!(
        p.root_motion_delta(0, -10., 10., true).unwrap(),
        RootDelta::default()
    );
    assert_eq!(p.events_between(0, 0., 1., true).unwrap().len(), 2);
}

#[test]
fn fractional_fps_event_boundaries_do_not_lose_or_repeat() {
    let mut c = clip();
    c.fps = 30.;
    c.frame_count = 72;
    c.events = vec![Event {
        frame: 9,
        name: "step".into(),
        parameter: String::new(),
    }];
    let p = pack(c);
    let period = p.clips[0].loop_period_s();
    for cycle in 0..1000 {
        let t = cycle as f64 * period + 9. / 30.;
        assert_eq!(p.events_between(0, t - 0.0001, t, true).unwrap().len(), 1);
        assert!(p.events_between(0, t, t + 0.0001, true).unwrap().is_empty());
    }
}
#[test]
fn root_small_interval_after_many_cycles_keeps_precision() {
    let mut c = clip();
    c.root = Some(RootTrack {
        bone: 0,
        translations: vec![[0., 0., 0.], [50., 0., 0.], [100., 0., 0.]],
        rotations: vec![[0., 0., 0., 1.]],
    });
    let p = pack(c);
    let d = p
        .root_motion_delta(0, 100_000_000.25, 100_000_000.5, true)
        .unwrap();
    near(d.translation[0], 25.);
}

fn encoded_track_fixture() -> (Vec<u8>, usize) {
    let mut payload = Vec::new();
    for (name, parent) in [("root", -1_i32), ("child", 0)] {
        string(&mut payload, name);
        payload.extend(parent.to_le_bytes());
        floats(&mut payload, &[0., 0., 0., 0., 0., 0., 1., 1., 1., 1.]);
    }
    let mut c = Vec::new();
    for s in ["three", "three", "cast", "rig"] {
        string(&mut c, s);
    }
    c.extend(1_u64.to_le_bytes());
    floats(&mut c, &[2.]);
    for v in [3_u32, 0, 0, 1, 1] {
        c.extend(v.to_le_bytes());
    }
    string(&mut c, "{}");
    c.extend(0_i32.to_le_bytes());
    c.extend(3_u32.to_le_bytes());
    floats(&mut c, &[0., 0., 0., 1., 0., 0., 2., 0., 0.]);
    c.extend(1_u32.to_le_bytes());
    for q in [0_i16, 0, 0, 32767] {
        c.extend(q.to_le_bytes());
    }
    let offset = 32 + payload.len() + 4 + c.len();
    c.extend(1_u16.to_le_bytes());
    c.extend([0, 7]);
    floats(&mut c, &[1., 1., 1.]);
    c.extend(3_u32.to_le_bytes());
    floats(&mut c, &[0., 0., 0., 2., 4., 6., 4., 8., 12.]);
    c.extend(3_u32.to_le_bytes());
    for q in [[0_i16, 0, 0, 32767], [0, 0, 32767, 0], [0, 0, 0, -32767]] {
        for v in q {
            c.extend(v.to_le_bytes());
        }
    }
    c.extend(1_u32.to_le_bytes());
    floats(&mut c, &[2., 2., 2.]);
    c.extend(1_u32.to_le_bytes());
    c.extend(1_u32.to_le_bytes());
    string(&mut c, "foot");
    string(&mut c, "sound");
    payload.extend((c.len() as u32).to_le_bytes());
    payload.extend(c);
    let mut b = b"FUSEANIM".to_vec();
    b.extend(0_u32.to_le_bytes());
    b.extend((32 + payload.len() as u64).to_le_bytes());
    b.extend(2_u32.to_le_bytes());
    b.extend(1_u32.to_le_bytes());
    b.extend(crc32(&payload).to_le_bytes());
    b.extend(payload);
    (b, offset)
}
#[test]
fn parser_round_trip_channels_root_and_event() {
    let (b, _) = encoded_track_fixture();
    let p = Pack::parse(&b).unwrap();
    let mut out = vec![Trs::default(); 2];
    p.sample(0, 0.25, false, &mut out).unwrap();
    assert_eq!(out[0].translation, [0.; 3]);
    assert_eq!(out[1].translation, [1., 2., 3.]);
    assert_eq!(out[1].scale, [2.; 3]);
    near(out[1].rotation[2], std::f32::consts::FRAC_1_SQRT_2);
    near(
        p.root_motion_delta(0, 0., 0.5, false).unwrap().translation[0],
        1.,
    );
    assert_eq!(
        p.events_between(0, 0., 0.5, false).unwrap()[0]
            .event
            .parameter,
        "sound"
    );
}
#[test]
fn parser_rejects_invalid_track_indices_modes_counts_weights_and_quaternions() {
    let (b, t) = encoded_track_fixture();
    for (offset, bytes) in [
        (t, vec![255, 255]),
        (t + 2, vec![2]),
        (t + 3, vec![0]),
        (t + 4, f32::NAN.to_le_bytes().to_vec()),
        (t + 4, 2_f32.to_le_bytes().to_vec()),
        (t + 16, u32::MAX.to_le_bytes().to_vec()),
        (t + 56, vec![0; 8]),
    ] {
        let mut invalid = b.clone();
        invalid[offset..offset + bytes.len()].copy_from_slice(&bytes);
        repair(&mut invalid);
        assert!(Pack::parse(&invalid).is_err());
    }
    for i in t..b.len() {
        let mut m = b.clone();
        m[i] ^= 255;
        repair(&mut m);
        let _ = Pack::parse(&m);
    }
}
