# Keep and dontwarn rules for release builds

-dontwarn com.google.errorprone.annotations.**
-dontwarn javax.annotation.**
-dontwarn org.slf4j.impl.**

# Kotlinx serialization and Ktor
-keepattributes *Annotation*,Signature,InnerClasses,EnclosingMethod

