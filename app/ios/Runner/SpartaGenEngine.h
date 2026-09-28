#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// The SpartaGen engine inside the app: Python running the repository's `spartagen` package, with ffmpeg
/// (FFmpegKit) as a function of the app — iOS apps cannot start programs.  It answers the Flutter side on
/// http://127.0.0.1:<port>/ with a secret token, like the engine process of the desktop apps.
@interface SpartaGenEngine : NSObject

/// Starts the engine (Python once; later calls find the engine running, or start its server again) and
/// returns its port — or nil, with what went wrong in `error`.  Blocks: call it off the main thread.
+ (nullable NSNumber *)startWithToken:(NSString *)token error:(NSString *_Nullable *_Nullable)error;

@end

NS_ASSUME_NONNULL_END
