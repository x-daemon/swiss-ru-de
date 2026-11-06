import AVFoundation
import AVKit
import SwiftUI
import UIKit

/// Floating subtitles over other apps (YouTube, Teams, …) using Picture in Picture: the two
/// lines are drawn into video frames and shown in a PiP window.
@MainActor
final class FloatingCaptions: NSObject, ObservableObject {
    @Published private(set) var isActive = false
    private(set) var isEnabled = false

    let displayLayer = AVSampleBufferDisplayLayer()
    private var controller: AVPictureInPictureController?
    private var lastTop = ""
    private var lastBottom = ""
    private let size = CGSize(width: 1280, height: 360)

    var isSupported: Bool { AVPictureInPictureController.isPictureInPictureSupported() }

    /// Prepares PiP; it then starts automatically when the app goes to the background
    /// (e.g. switching to YouTube) or with `toggle()`.
    func enable() {
        guard controller == nil, isSupported else { return }
        isEnabled = true
        displayLayer.videoGravity = .resizeAspect
        let source = AVPictureInPictureController.ContentSource(sampleBufferDisplayLayer: displayLayer,
                                                                 playbackDelegate: self)
        let pip = AVPictureInPictureController(contentSource: source)
        pip.delegate = self
        pip.canStartPictureInPictureAutomaticallyFromInline = true
        controller = pip
        show(top: lastTop.isEmpty ? "Swiss RU-DE" : lastTop, bottom: lastBottom.isEmpty ? "…" : lastBottom)
    }

    func toggle() {
        if AVAudioSession.sharedInstance().category != .playAndRecord {
            try? AudioSessionManager.activate(.playback) // PiP needs an active audio session
        }
        enable()
        guard let controller else { return }
        if controller.isPictureInPictureActive {
            controller.stopPictureInPicture()
        } else {
            controller.startPictureInPicture()
        }
    }

    func show(top: String, bottom: String) {
        lastTop = top
        lastBottom = bottom
        guard isEnabled, let buffer = Self.render(top: top, bottom: bottom, size: size),
              let sample = Self.sampleBuffer(buffer) else { return }
        if displayLayer.status == .failed { displayLayer.flush() }
        displayLayer.enqueue(sample)
    }

    // MARK: drawing

    private static func render(top: String, bottom: String, size: CGSize) -> CVPixelBuffer? {
        let width = Int(size.width), height = Int(size.height)
        let attributes: [String: Any] = [
            kCVPixelBufferCGImageCompatibilityKey as String: true,
            kCVPixelBufferCGBitmapContextCompatibilityKey as String: true,
            kCVPixelBufferIOSurfacePropertiesKey as String: [String: Any](),
        ]
        var pixelBuffer: CVPixelBuffer?
        CVPixelBufferCreate(kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA,
                            attributes as CFDictionary, &pixelBuffer)
        guard let pixelBuffer else { return nil }
        CVPixelBufferLockBaseAddress(pixelBuffer, [])
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, []) }
        guard let context = CGContext(
            data: CVPixelBufferGetBaseAddress(pixelBuffer), width: width, height: height,
            bitsPerComponent: 8, bytesPerRow: CVPixelBufferGetBytesPerRow(pixelBuffer),
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedFirst.rawValue | CGBitmapInfo.byteOrder32Little.rawValue
        ) else { return nil }

        context.translateBy(x: 0, y: CGFloat(height)) // UIKit coordinates
        context.scaleBy(x: 1, y: -1)
        UIGraphicsPushContext(context)
        defer { UIGraphicsPopContext() }

        UIColor(Theme.panel).setFill()
        UIRectFill(CGRect(origin: .zero, size: size))
        let pad: CGFloat = 36
        UIColor(Theme.topAccent).setFill()
        UIRectFill(CGRect(x: pad - 18, y: 34, width: 6, height: 104))
        UIColor(Theme.bottomAccent).setFill()
        UIRectFill(CGRect(x: pad - 18, y: 170, width: 6, height: 160))

        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byTruncatingHead // keep the newest words visible
        let topAttributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 42, weight: .regular),
            .foregroundColor: UIColor(Theme.oldText),
            .paragraphStyle: paragraph,
        ]
        let bottomAttributes: [NSAttributedString.Key: Any] = [
            .font: UIFont.systemFont(ofSize: 54, weight: .semibold),
            .foregroundColor: UIColor.white,
            .paragraphStyle: paragraph,
        ]
        let textWidth = size.width - pad * 2
        (top as NSString).draw(with: CGRect(x: pad, y: 30, width: textWidth, height: 112),
                               options: [.usesLineFragmentOrigin, .truncatesLastVisibleLine],
                               attributes: topAttributes, context: nil)
        (bottom as NSString).draw(with: CGRect(x: pad, y: 165, width: textWidth, height: 170),
                                  options: [.usesLineFragmentOrigin, .truncatesLastVisibleLine],
                                  attributes: bottomAttributes, context: nil)
        return pixelBuffer
    }

    private static func sampleBuffer(_ pixelBuffer: CVPixelBuffer) -> CMSampleBuffer? {
        var format: CMVideoFormatDescription?
        CMVideoFormatDescriptionCreateForImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: pixelBuffer,
                                                     formatDescriptionOut: &format)
        guard let format else { return nil }
        var timing = CMSampleTimingInfo(duration: CMTime(value: 1, timescale: 30),
                                        presentationTimeStamp: CMClockGetTime(CMClockGetHostTimeClock()),
                                        decodeTimeStamp: .invalid)
        var sample: CMSampleBuffer?
        CMSampleBufferCreateReadyWithImageBuffer(allocator: kCFAllocatorDefault, imageBuffer: pixelBuffer,
                                                 formatDescription: format, sampleTiming: &timing,
                                                 sampleBufferOut: &sample)
        guard let sample else { return nil }
        if let attachments = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: true),
           CFArrayGetCount(attachments) > 0 {
            let dict = unsafeBitCast(CFArrayGetValueAtIndex(attachments, 0), to: CFMutableDictionary.self)
            CFDictionarySetValue(dict,
                                 Unmanaged.passUnretained(kCMSampleAttachmentKey_DisplayImmediately).toOpaque(),
                                 Unmanaged.passUnretained(kCFBooleanTrue).toOpaque())
        }
        return sample
    }
}

extension FloatingCaptions: AVPictureInPictureControllerDelegate {
    nonisolated func pictureInPictureControllerDidStartPictureInPicture(_ controller: AVPictureInPictureController) {
        Task { @MainActor in self.isActive = true }
    }

    nonisolated func pictureInPictureControllerDidStopPictureInPicture(_ controller: AVPictureInPictureController) {
        Task { @MainActor in self.isActive = false }
    }
}

extension FloatingCaptions: AVPictureInPictureSampleBufferPlaybackDelegate {
    nonisolated func pictureInPictureController(_ controller: AVPictureInPictureController, setPlaying playing: Bool) {}

    nonisolated func pictureInPictureControllerTimeRangeForPlayback(_ controller: AVPictureInPictureController) -> CMTimeRange {
        CMTimeRange(start: .negativeInfinity, duration: .positiveInfinity) // live
    }

    nonisolated func pictureInPictureControllerIsPlaybackPaused(_ controller: AVPictureInPictureController) -> Bool {
        false
    }

    nonisolated func pictureInPictureController(_ controller: AVPictureInPictureController,
                                                didTransitionToRenderSize newRenderSize: CMVideoDimensions) {}

    nonisolated func pictureInPictureController(_ controller: AVPictureInPictureController,
                                                skipByInterval skipInterval: CMTime,
                                                completion completionHandler: @escaping () -> Void) {
        completionHandler()
    }
}

/// Hosts the PiP display layer in the view hierarchy (required by iOS); doubles as a small
/// live preview of the floating captions.
struct FloatingPreview: UIViewRepresentable {
    let layer: AVSampleBufferDisplayLayer

    func makeUIView(context: Context) -> LayerView {
        let view = LayerView()
        view.hosted = layer
        view.layer.addSublayer(layer)
        view.clipsToBounds = true
        view.layer.cornerRadius = 6
        return view
    }

    func updateUIView(_ uiView: LayerView, context: Context) {}

    final class LayerView: UIView {
        var hosted: CALayer?
        override func layoutSubviews() {
            super.layoutSubviews()
            hosted?.frame = bounds
        }
    }
}
