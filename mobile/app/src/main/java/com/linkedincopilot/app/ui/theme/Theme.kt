package com.linkedincopilot.app.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import androidx.core.view.WindowCompat

/**
 * A restrained dark-first palette: deep neutral ground, one accent, and
 * semantic colours reserved for status. No gradients, no glow.
 */
private val Ink = Color(0xFF0B1220)
private val Surface1 = Color(0xFF121A29)
private val Surface2 = Color(0xFF1A2435)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF7DD3A0),
    onPrimary = Color(0xFF04150C),
    primaryContainer = Color(0xFF1E3A2C),
    onPrimaryContainer = Color(0xFFB7EFCC),
    secondary = Color(0xFF8AB4F8),
    onSecondary = Color(0xFF06172E),
    background = Ink,
    onBackground = Color(0xFFE6EAF2),
    surface = Surface1,
    onSurface = Color(0xFFE6EAF2),
    surfaceVariant = Surface2,
    onSurfaceVariant = Color(0xFF9AA7BD),
    outline = Color(0xFF2C3A50),
    error = Color(0xFFF2857F),
    onError = Color(0xFF2A0A08),
    errorContainer = Color(0xFF3B1614),
    onErrorContainer = Color(0xFFFFD9D6),
)

private val LightColors = lightColorScheme(
    primary = Color(0xFF1B7A4B),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFB7EFCC),
    onPrimaryContainer = Color(0xFF04220F),
    secondary = Color(0xFF2A5DB0),
    background = Color(0xFFF7F9FC),
    onBackground = Color(0xFF121A29),
    surface = Color(0xFFFFFFFF),
    onSurface = Color(0xFF121A29),
    surfaceVariant = Color(0xFFEDF1F7),
    onSurfaceVariant = Color(0xFF57627A),
    error = Color(0xFFB3261E),
)

private val AppTypography = Typography(
    headlineSmall = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold,
        fontSize = 22.sp, lineHeight = 28.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.SemiBold,
        fontSize = 19.sp, lineHeight = 25.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium,
        fontSize = 16.sp, lineHeight = 22.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.Normal,
        fontSize = 16.sp, lineHeight = 24.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.Normal,
        fontSize = 14.sp, lineHeight = 20.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium,
        fontSize = 14.sp, letterSpacing = 0.1.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = FontFamily.Default, fontWeight = FontWeight.Medium,
        fontSize = 11.sp, letterSpacing = 0.4.sp,
    ),
)

@Composable
fun CopilotTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colors = if (darkTheme) DarkColors else LightColors
    val view = LocalView.current
    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
        }
    }
    MaterialTheme(colorScheme = colors, typography = AppTypography, content = content)
}
