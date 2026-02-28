import networkx as nx
from pyvis.network import Network

# 1. Creazione del grafo di esempio
graph = nx.Graph()
graph.add_edges_from([(1, 2), (1, 3), (2, 4), (2, 5), (3, 6), (3, 7)])

# 2. Implementazione BFS
def bfs(graph, start):
    visited = []
    queue = [start]
    visited.append(start)

    while queue:
        node = queue.pop(0)
        for neighbor in graph.neighbors(node):
            if neighbor not in visited:
                visited.append(neighbor)
                queue.append(neighbor)
    return visited

# Esecuzione BFS
start_node = 1
bfs_result = bfs(graph, start_node)
print(f"Risultato BFS partendo dal nodo {start_node}: {bfs_result}")

# 3. Visualizzazione web con pyvis
net = Network(notebook=False, height="500px", width="100%")
net.from_nx(graph)
net.show("sandbox/bfs_graph_2.html", local=False)