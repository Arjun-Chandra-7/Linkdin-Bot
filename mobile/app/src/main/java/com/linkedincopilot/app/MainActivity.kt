package com.linkedincopilot.app

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarMonth
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.InsertChart
import androidx.compose.material.icons.filled.People
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.linkedincopilot.app.notifications.NotificationWorker
import com.linkedincopilot.app.ui.AppViewModel
import com.linkedincopilot.app.ui.screens.AnalyticsScreen
import com.linkedincopilot.app.ui.screens.ApprovalDetailScreen
import com.linkedincopilot.app.ui.screens.ApprovalsScreen
import com.linkedincopilot.app.ui.screens.CalendarScreen
import com.linkedincopilot.app.ui.screens.HomeScreen
import com.linkedincopilot.app.ui.screens.NetworkScreen
import com.linkedincopilot.app.ui.screens.PairingScreen
import com.linkedincopilot.app.ui.screens.SettingsScreen
import com.linkedincopilot.app.ui.theme.CopilotTheme

private data class Tab(val route: String, val label: String, val icon: ImageVector)

private val TABS = listOf(
    Tab("home", "Home", Icons.Filled.Home),
    Tab("approvals", "Approvals", Icons.Filled.CheckCircle),
    Tab("calendar", "Calendar", Icons.Filled.CalendarMonth),
    Tab("network", "People", Icons.Filled.People),
    Tab("analytics", "Analytics", Icons.Filled.InsertChart),
)

class MainActivity : ComponentActivity() {

    private val notificationPermission =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        NotificationWorker.ensureChannel(this)
        NotificationWorker.schedule(this)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent { CopilotTheme { CopilotApp() } }
    }
}

@Composable
private fun CopilotApp() {
    val vm: AppViewModel = viewModel()
    val state by vm.state.collectAsStateWithLifecycle()
    val navController = rememberNavController()
    val snackbar = remember { SnackbarHostState() }

    // Surface every message and error as one line the user can act on.
    LaunchedEffect(state.message, state.error) {
        val text = state.message ?: state.error?.let { error ->
            listOfNotNull(error.message, error.recovery).joinToString(" ")
        }
        if (text != null) {
            snackbar.showSnackbar(text)
            vm.clearMessage()
        }
    }

    if (!state.paired) {
        Scaffold(snackbarHost = { SnackbarHost(snackbar) }) { padding ->
            Box(Modifier.padding(padding)) {
                PairingScreen(vm, state) { }
            }
        }
        return
    }

    val backStack by navController.currentBackStackEntryAsState()
    val currentRoute = backStack?.destination?.hierarchy?.firstOrNull()?.route
    val showBar = TABS.any { it.route == currentRoute } || currentRoute == "settings"

    Scaffold(
        snackbarHost = { SnackbarHost(snackbar) },
        bottomBar = {
            if (showBar) {
                NavigationBar {
                    TABS.forEach { tab ->
                        val selected = currentRoute == tab.route
                        NavigationBarItem(
                            selected = selected,
                            onClick = {
                                navController.navigate(tab.route) {
                                    popUpTo(navController.graph.findStartDestination().id) {
                                        saveState = true
                                    }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = {
                                if (tab.route == "approvals" && (state.home?.pendingApprovals ?: 0) > 0) {
                                    BadgedBox(badge = {
                                        Badge { Text("${state.home?.pendingApprovals}") }
                                    }) { Icon(tab.icon, contentDescription = tab.label) }
                                } else {
                                    Icon(tab.icon, contentDescription = tab.label)
                                }
                            },
                            label = { Text(tab.label) },
                        )
                    }
                }
            }
        },
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = "home",
            modifier = Modifier.padding(padding),
        ) {
            composable("home") {
                LaunchedEffect(Unit) { vm.refreshAll() }
                HomeScreen(
                    vm, state,
                    onOpenApprovals = { navController.navigate("approvals") },
                    onOpenCalendar = { navController.navigate("calendar") },
                    onOpenNetwork = { navController.navigate("network") },
                    onOpenAnalytics = { navController.navigate("analytics") },
                    onOpenSettings = { navController.navigate("settings") },
                )
            }
            composable("approvals") {
                LaunchedEffect(Unit) { vm.refreshAll() }
                ApprovalsScreen(vm, state) { id -> navController.navigate("draft/$id") }
            }
            composable("draft/{id}") { entry ->
                val id = entry.arguments?.getString("id")?.toIntOrNull()
                if (id == null) navController.popBackStack()
                else ApprovalDetailScreen(id, vm, state) { navController.popBackStack() }
            }
            composable("calendar") {
                CalendarScreen(vm, state) { id -> navController.navigate("draft/$id") }
            }
            composable("network") { NetworkScreen(vm, state) }
            composable("analytics") { AnalyticsScreen(vm, state) }
            composable("settings") {
                SettingsScreen(vm, state) { navController.navigate("home") }
            }
        }
    }
}
