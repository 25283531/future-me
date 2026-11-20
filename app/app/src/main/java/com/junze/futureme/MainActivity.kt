package com.junze.futureme

import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.MailOutline
import androidx.compose.material.icons.filled.Person
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.junze.futureme.ui.daily.DailyScreen
import com.junze.futureme.ui.daily.DailyViewModel
import com.junze.futureme.ui.home.HomeScreen
import com.junze.futureme.ui.home.HomeViewModel
import com.junze.futureme.ui.home.WishDetailScreen
import com.junze.futureme.ui.letters.LetterDetailScreen
import com.junze.futureme.ui.letters.LetterDetailViewModel
import com.junze.futureme.ui.letters.LettersScreen
import com.junze.futureme.ui.letters.LettersViewModel
import com.junze.futureme.ui.account.AccountScreen
import com.junze.futureme.ui.account.AccountViewModel
import com.junze.futureme.ui.me.MeScreen
import com.junze.futureme.ui.me.MeViewModel
import com.junze.futureme.ui.privacy.PrivacyScreen
import com.junze.futureme.ui.privacy.PrivacyViewModel
import com.junze.futureme.ui.nav.Routes
import com.junze.futureme.ui.theme.FutureMeTheme

class MainActivity : ComponentActivity() {

    private val notificationPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { /* best effort */ }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        requestNotificationPermissionIfNeeded()
        setContent {
            FutureMeTheme {
                MainScaffold(app = application as FutureMeApp)
            }
        }
    }

    private fun requestNotificationPermissionIfNeeded() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val granted = ContextCompat.checkSelfPermission(
                this, Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
            if (!granted) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }
}

private data class Tab(
    val route: String,
    val labelRes: Int,
    val icon: ImageVector
)

private val TABS = listOf(
    Tab(Routes.HOME, R.string.nav_home, Icons.Filled.Home),
    Tab(Routes.LETTERS, R.string.nav_letters, Icons.Filled.MailOutline),
    Tab(Routes.DAILY, R.string.nav_daily, Icons.Filled.DateRange),
    Tab(Routes.ME, R.string.nav_me, Icons.Filled.Person)
)

/** Generic factory for ViewModels wired by hand (no DI framework). */
inline fun <reified T : ViewModel> vmFactory(crossinline create: () -> T) =
    object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T2 : ViewModel> create(modelClass: Class<T2>): T2 = create() as T2
    }

@Composable
private fun MainScaffold(app: FutureMeApp) {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentDestination = navBackStackEntry?.destination

    Scaffold(
        bottomBar = {
            NavigationBar {
                TABS.forEach { tab ->
                    val selected = currentDestination?.hierarchy?.any { it.route == tab.route } == true
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
                        icon = { Icon(tab.icon, contentDescription = null) },
                        label = { Text(text = stringResource(tab.labelRes)) }
                    )
                }
            }
        }
    ) { innerPadding ->
        NavHost(
            navController = navController,
            startDestination = Routes.HOME,
            modifier = Modifier.padding(innerPadding)
        ) {
            composable(Routes.HOME) {
                val vm: HomeViewModel = viewModel(
                    factory = vmFactory { HomeViewModel(app.repository, app.settings) }
                )
                HomeScreen(
                    viewModel = vm,
                    onWishClick = { wishId -> navController.navigate(Routes.wishDetail(wishId)) }
                )
            }
            composable(
                route = Routes.WISH_DETAIL,
                arguments = listOf(navArgument("wishId") { type = NavType.StringType })
            ) { backStackEntry ->
                val wishId = backStackEntry.arguments?.getString("wishId") ?: return@composable
                val vm: HomeViewModel = viewModel(
                    factory = vmFactory { HomeViewModel(app.repository, app.settings) }
                )
                WishDetailScreen(
                    wishId = wishId,
                    viewModel = vm,
                    onLetterClick = { letterId ->
                        navController.navigate(Routes.letterDetail(letterId))
                    },
                    onBack = { navController.popBackStack() }
                )
            }
            composable(Routes.LETTERS) {
                val vm: LettersViewModel = viewModel(
                    factory = vmFactory { LettersViewModel(app.repository, app.settings) }
                )
                LettersScreen(
                    viewModel = vm,
                    onLetterClick = { letterId ->
                        navController.navigate(Routes.letterDetail(letterId))
                    }
                )
            }
            composable(
                route = Routes.LETTER_DETAIL,
                arguments = listOf(navArgument("letterId") { type = NavType.StringType })
            ) { backStackEntry ->
                val letterId = backStackEntry.arguments?.getString("letterId") ?: return@composable
                val vm: LetterDetailViewModel = viewModel(
                    factory = vmFactory {
                        LetterDetailViewModel(app.repository, app.audioPlayer)
                    }
                )
                // Load the letter when this destination is entered.
                LaunchedEffect(letterId) { vm.load(letterId) }
                LetterDetailScreen(
                    viewModel = vm,
                    onBack = { navController.popBackStack() }
                )
            }
            composable(Routes.DAILY) {
                val vm: DailyViewModel = viewModel(
                    factory = vmFactory { DailyViewModel(app.repository, app.settings) }
                )
                DailyScreen(viewModel = vm)
            }
            composable(Routes.ME) {
                val vm: MeViewModel = viewModel(
                    factory = vmFactory { MeViewModel(app.repository) }
                )
                MeScreen(
                    viewModel = vm,
                    onAccountClick = { navController.navigate(Routes.ACCOUNT) },
                    onPrivacyClick = { navController.navigate(Routes.PRIVACY) }
                )
            }
            composable(Routes.ACCOUNT) {
                val vm: AccountViewModel = viewModel(
                    factory = vmFactory { AccountViewModel(app.repository) }
                )
                AccountScreen(
                    viewModel = vm,
                    onPrivacyClick = { navController.navigate(Routes.PRIVACY) },
                    onBack = { navController.popBackStack() }
                )
            }
            composable(Routes.PRIVACY) {
                val vm: PrivacyViewModel = viewModel(
                    factory = vmFactory { PrivacyViewModel(app.repository) }
                )
                PrivacyScreen(
                    viewModel = vm,
                    onBack = { navController.popBackStack() }
                )
            }
        }
    }
}
