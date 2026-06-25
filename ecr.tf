resource "aws_ecr_repository" "ansible_codebuild" {
  name                 = var.ansible_codebuild_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.ansible_codebuild_image_repository_name
    Purpose   = "ansible-codebuild-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "ansible_codebuild" {
  repository = aws_ecr_repository.ansible_codebuild.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Ansible CodeBuild images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "internal_git" {
  name                 = var.internal_git_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.internal_git_image_repository_name
    Purpose   = "internal-git-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "internal_git" {
  repository = aws_ecr_repository.internal_git.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 internal Git images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "argocd" {
  name                 = var.argocd_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.argocd_image_repository_name
    Purpose   = "argocd-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "argocd" {
  repository = aws_ecr_repository.argocd.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Argo CD images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "argocd_redis" {
  name                 = var.argocd_redis_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.argocd_redis_image_repository_name
    Purpose   = "argocd-redis-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "argocd_redis" {
  repository = aws_ecr_repository.argocd_redis.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Argo CD Redis images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}
resource "aws_ecr_repository" "monitoring_tempo" {
  name                 = "financial/monitoring/tempo"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "tempo"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_tempo" {
  repository = aws_ecr_repository.monitoring_tempo.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Tempo images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "monitoring_grafana" {
  name                 = "financial/monitoring/grafana"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "grafana"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_grafana" {
  repository = aws_ecr_repository.monitoring_grafana.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Grafana images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "monitoring_loki" {
  name                 = "financial/monitoring/loki"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "loki"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_loki" {
  repository = aws_ecr_repository.monitoring_loki.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Loki images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "monitoring_thanos" {
  name                 = "financial/monitoring/thanos"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "thanos"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_thanos" {
  repository = aws_ecr_repository.monitoring_thanos.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Thanos images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "monitoring_alertmanager" {
  name                 = "financial/monitoring/alertmanager"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "alertmanager"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_alertmanager" {
  repository = aws_ecr_repository.monitoring_alertmanager.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Alertmanager images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "monitoring_alloy" {
  name                 = "financial/monitoring/alloy"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "alloy"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_alloy" {
  repository = aws_ecr_repository.monitoring_alloy.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Alloy images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "istio_pilot" {
  name                 = "${var.istio_image_repository_prefix}/pilot"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/pilot"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "istio_proxyv2" {
  name                 = "${var.istio_image_repository_prefix}/proxyv2"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/proxyv2"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "istio_install_cni" {
  name                 = "${var.istio_image_repository_prefix}/install-cni"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/install-cni"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "istio_ztunnel" {
  name                 = "${var.istio_image_repository_prefix}/ztunnel"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "${var.istio_image_repository_prefix}/ztunnel"
    Purpose   = "istio-ambient-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "istio_pilot" {
  repository = aws_ecr_repository.istio_pilot.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio pilot images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "istio_proxyv2" {
  repository = aws_ecr_repository.istio_proxyv2.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio proxyv2 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "istio_install_cni" {
  repository = aws_ecr_repository.istio_install_cni.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio install-cni images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "istio_ztunnel" {
  repository = aws_ecr_repository.istio_ztunnel.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Istio ztunnel images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "teleport" {
  name                 = var.teleport_image_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = var.teleport_image_repository_name
    Purpose   = "teleport-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "teleport" {
  repository = aws_ecr_repository.teleport.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Teleport images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "finops_temporal" {
  name                 = "financial/mas/finops/temporal"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/mas/finops/temporal"
    Purpose   = "finops-temporal-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "finops_temporal" {
  repository = aws_ecr_repository.finops_temporal.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 FinOps Temporal images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "temporal_server" {
  name                 = "financial/mas/temporal/server"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/mas/temporal/server"
    Purpose   = "temporal-server-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "temporal_server" {
  repository = aws_ecr_repository.temporal_server.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Temporal Server images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "temporal_ui" {
  name                 = "financial/mas/temporal/ui"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/mas/temporal/ui"
    Purpose   = "temporal-ui-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "temporal_ui" {
  repository = aws_ecr_repository.temporal_ui.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Temporal UI images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "finops_postgres" {
  name                 = "financial/mas/finops/postgres"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/mas/finops/postgres"
    Purpose   = "finops-postgres-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "finops_postgres" {
  repository = aws_ecr_repository.finops_postgres.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 FinOps Postgres images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "pause" {
  name                 = "financial/pause"
  image_tag_mutability = "MUTABLE"
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = {
    Name      = "financial/pause"
    Purpose   = "k3s-pause-image"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "aws_load_balancer_controller" {
  name                 = "financial/system/aws-load-balancer-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/system/aws-load-balancer-controller"
    Purpose   = "aws-load-balancer-controller-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_repository" "aws_load_balancer_controller_monitoring" {
  name                 = "financial/monitoring/aws-load-balancer-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/monitoring/aws-load-balancer-controller"
    Purpose   = "aws-load-balancer-controller-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_ecr_lifecycle_policy" "aws_load_balancer_controller_monitoring" {
  repository = aws_ecr_repository.aws_load_balancer_controller_monitoring.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 AWS Load Balancer Controller images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_lifecycle_policy" "aws_load_balancer_controller" {
  repository = aws_ecr_repository.aws_load_balancer_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 AWS Load Balancer Controller images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "observability_indexer" {
  name                 = "financial/monitoring/observability-indexer"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/monitoring/observability-indexer"
    Purpose   = "observability-indexer-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "observability_indexer" {
  repository = aws_ecr_repository.observability_indexer.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Observability Indexer images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "external_secrets" {
  name                 = "external-secrets/external-secrets"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "external-secrets/external-secrets"
    Purpose   = "eso-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "external_secrets" {
  repository = aws_ecr_repository.external_secrets.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 ESO images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyverno" {
  name                 = "financial/kyverno/kyverno"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/kyverno"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno" {
  repository = aws_ecr_repository.kyverno.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyvernopre" {
  name                 = "financial/kyverno/kyvernopre"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/kyvernopre"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyvernopre" {
  repository = aws_ecr_repository.kyvernopre.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyverno_background_controller" {
  name                 = "financial/kyverno/background-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/background-controller"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_background_controller" {
  repository = aws_ecr_repository.kyverno_background_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyverno_cleanup_controller" {
  name                 = "financial/kyverno/cleanup-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/cleanup-controller"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_cleanup_controller" {
  repository = aws_ecr_repository.kyverno_cleanup_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyverno_reports_controller" {
  name                 = "financial/kyverno/reports-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/reports-controller"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_reports_controller" {
  repository = aws_ecr_repository.kyverno_reports_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyverno_cli" {
  name                 = "financial/kyverno/kyverno-cli"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/kyverno-cli"
    Purpose   = "kyverno-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_cli" {
  repository = aws_ecr_repository.kyverno_cli.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "kyverno_kubectl" {
  name                 = "financial/kyverno/kubectl"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/kyverno/kubectl"
    Purpose   = "kyverno-cleanup-jobs-runtime"
    ManagedBy = "terraform"
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_ecr_lifecycle_policy" "kyverno_kubectl" {
  repository = aws_ecr_repository.kyverno_kubectl.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Kyverno kubectl images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "demo_app_backend" {
  name                 = "financial/demo-app-backend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/demo-app-backend"
    Purpose   = "demo-app-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "demo_app_backend" {
  repository = aws_ecr_repository.demo_app_backend.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 demo-app-backend images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "demo_app_frontend" {
  name                 = "financial/demo-app-frontend"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "financial/demo-app-frontend"
    Purpose   = "demo-app-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "demo_app_frontend" {
  repository = aws_ecr_repository.demo_app_frontend.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 demo-app-frontend images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "metrics_server" {
  name                 = "financial/monitoring/metrics-server"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "metrics-server"
  }
}

resource "aws_ecr_lifecycle_policy" "metrics_server" {
  repository = aws_ecr_repository.metrics_server.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 metrics-server images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
resource "aws_ecr_repository" "monitoring_kube_state_metrics" {
  name                 = "financial/monitoring/kube-state-metrics"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = {
    Project   = "ilpoomjinro"
    ManagedBy = "terraform"
    Service   = "monitoring"
    Component = "kube-state-metrics"
  }
}

resource "aws_ecr_lifecycle_policy" "monitoring_kube_state_metrics" {
  repository = aws_ecr_repository.monitoring_kube_state_metrics.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 kube-state-metrics images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "velero" {
  name                 = "velero/velero"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "velero/velero"
    Purpose   = "velero-backup-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "velero" {
  repository = aws_ecr_repository.velero.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Velero images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "velero_plugin_aws" {
  name                 = "velero/velero-plugin-for-aws"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "velero/velero-plugin-for-aws"
    Purpose   = "velero-backup-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "velero_plugin_aws" {
  repository = aws_ecr_repository.velero_plugin_aws.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 Velero AWS plugin images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}

resource "aws_ecr_repository" "snapshot_controller" {
  name                 = "sig-storage/snapshot-controller"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name      = "sig-storage/snapshot-controller"
    Purpose   = "csi-snapshot-controller-runtime"
    ManagedBy = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "snapshot_controller" {
  repository = aws_ecr_repository.snapshot_controller.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the last 10 snapshot-controller images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = {
        type = "expire"
      }
    }]
  })
}
