(function () {
    var scanner = new DependencyScanner();
    var result = scanner.rebuildGraph();
    gs.info('Dependency Tracker nightly rebuild: ' + result.nodes + ' nodes, ' + result.edges + ' edges');
})();
