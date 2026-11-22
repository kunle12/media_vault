/*
 * Cross-tab logout listener for proxied apps that we do not build ourselves.
 *
 * The console posts {type:"logout"} on the "kunle-guard" BroadcastChannel;
 * every tab of this origin listening here navigates to the guard login. A tab
 * cannot be closed by another tab, so this is the closest honest behaviour.
 *
 * Keep the channel name in sync with web/src/lib/logout.ts and
 * web/src/app.html. Injected into Grafana by nginx; chat-ui will adopt it
 * after its revamp (deliberately untouched for now).
 */
(function () {
	try {
		var channel = new BroadcastChannel('kunle-guard');
		channel.addEventListener('message', function (event) {
			if (event.data && event.data.type === 'logout' && window.location.pathname !== '/login') {
				window.location.replace('/login');
			}
		});
	} catch (e) {
		/* no BroadcastChannel: the app stays usable until its next request */
	}
})();
